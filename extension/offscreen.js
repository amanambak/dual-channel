// offscreen.js — Offscreen document
// Owns tab audio capture and the persistent backend WebSocket session.
// Supports dual-channel: tab audio (customer) + microphone (agent)

let audioContext;
let mediaStream;
let micStream;
let source;
let micSource;
let workletCustomer = null;
let workletAgent = null;
let backendSocket;
let currentSessionId = null;
let isAgentMicPaused = false;
let backendSessionReady = false;
let queuedAudioFrames = [];

const MAX_QUEUED_AUDIO_FRAMES = 800;

chrome.runtime.onMessage.addListener((message) => {
  if (message.type === 'START_CAPTURE' && message.offscreen) {
    startCapture(message.streamId, message.captureMode);
  } else if (message.type === 'STOP_CAPTURE' && message.offscreen) {
    stopCapture();
  } else if (message.type === 'SET_AGENT_MIC_PAUSED' && message.offscreen) {
    setAgentMicPaused(Boolean(message.paused));
  } else if (message.type === 'REQUEST_SUMMARY' && message.offscreen) {
    requestSummary(message.requestId);
  } else if (message.type === 'SET_SESSION_LEAD_CONTEXT' && message.offscreen) {
    sendLeadContextToBackend(message);
  }
});

async function startCapture(streamId, captureMode = 'gmeet') {
  try {
    isAgentMicPaused = false;
    const shouldCaptureMic = captureMode === 'gmeet' || captureMode === 'rtc';
    let hasMicChannel = false;

    // Get tab audio
    mediaStream = await navigator.mediaDevices.getUserMedia({
      audio: {
        mandatory: {
          chromeMediaSource: 'tab',
          chromeMediaSourceId: streamId
        }
      },
      video: false
    });

    audioContext = new AudioContext({
      sampleRate: 24000
    });

    // Create gain nodes for each channel
    const tabGain = audioContext.createGain();
    const micGain = audioContext.createGain();

    // Tab audio source (channel 0 - customer)
    source = audioContext.createMediaStreamSource(mediaStream);
    source.connect(tabGain);
    // Tab audio to local playback (so agent can hear the customer)
    tabGain.connect(audioContext.destination);

    if (shouldCaptureMic) {
      // Get microphone (channel 1 - agent)
      try {
        micStream = await navigator.mediaDevices.getUserMedia({
          audio: {
            echoCancellation: false,
            noiseSuppression: false,
            autoGainControl: false
          }
        });
        micSource = audioContext.createMediaStreamSource(micStream);
        micSource.connect(micGain);
        hasMicChannel = true;
        // NOTE: Do NOT connect micGain to audioContext.destination to avoid echo
      } catch (micErr) {
        const isDenied = micErr.name === 'NotAllowedError' || micErr.name === 'PermissionDeniedError';
        const errorMsg = isDenied
          ? 'Microphone permission denied. Grant mic access and try again.'
          : `Microphone unavailable: ${micErr.message}`;
        console.warn('[offscreen] Mic access failed:', errorMsg);
        chrome.runtime.sendMessage({
          type: 'API_ERROR',
          source: 'Mic',
          message: errorMsg
        }).catch(() => {});
        micStream = null;
        micSource = null;
      }
    }

    const backendConnection = openBackendConnection(captureMode, hasMicChannel);
    await setupDualChannelWorklets(tabGain, hasMicChannel ? micGain : null);
    await backendConnection;

  } catch (err) {
    chrome.runtime.sendMessage({
      type: 'API_ERROR',
      source: 'Offscreen',
      message: `Failed to start audio capture: ${err.message}`
    }).catch(() => {});
  }
}

/**
 * Sends one prepared audio chunk over the backend WebSocket with a single-byte
 * channel prefix.
 *
 * @param {number} channelByte - 0 = customer, 1 = agent
 * @param {ArrayBuffer} audioBuffer - 25 ms mono Int16 PCM payload
 */
function sendChannelFrame(channelByte, audioBuffer, shouldSkip = () => false) {
  if (shouldSkip()) {
    return false;
  }
  if (!backendSocket || backendSocket.readyState !== WebSocket.OPEN || !backendSessionReady) {
    queueAudioFrame(channelByte, audioBuffer);
    return true;
  }
  return sendPreparedChannelFrame(channelByte, audioBuffer);
}

function queueAudioFrame(channelByte, audioBuffer) {
  if (!audioBuffer?.byteLength) {
    return;
  }
  queuedAudioFrames.push({
    channelByte,
    audioBuffer: audioBuffer.slice(0)
  });
  if (queuedAudioFrames.length > MAX_QUEUED_AUDIO_FRAMES) {
    queuedAudioFrames.splice(0, queuedAudioFrames.length - MAX_QUEUED_AUDIO_FRAMES);
  }
}

function flushQueuedAudioFrames() {
  if (!backendSocket || backendSocket.readyState !== WebSocket.OPEN || !backendSessionReady) {
    return;
  }
  const frames = queuedAudioFrames;
  queuedAudioFrames = [];
  for (const frame of frames) {
    sendPreparedChannelFrame(frame.channelByte, frame.audioBuffer);
  }
}

function sendPreparedChannelFrame(channelByte, audioBuffer) {
  const channelBuffer = new ArrayBuffer(audioBuffer.byteLength + 1);
  const view = new Uint8Array(channelBuffer);
  view[0] = channelByte;
  view.set(new Uint8Array(audioBuffer), 1);
  backendSocket.send(channelBuffer);
  return true;
}

async function setupDualChannelWorklets(tabGain, micGain) {
  // Worklet for tab audio (channel 0 - customer)
  await audioContext.audioWorklet.addModule('capture-worklet.js');
  if (audioContext.state === 'suspended') {
    await audioContext.resume();
  }

  workletCustomer = new AudioWorkletNode(audioContext, 'capture-worklet');
  tabGain.connect(workletCustomer);
  workletCustomer.port.onmessage = (event) => {
    sendChannelFrame(0, event.data);
  };

  // Worklet for microphone (channel 1 - agent)
  if (micGain) {
    workletAgent = new AudioWorkletNode(audioContext, 'capture-worklet');
    micGain.connect(workletAgent);
    workletAgent.port.onmessage = (event) => {
      sendChannelFrame(1, event.data, () => isAgentMicPaused);
    };
  }
}

function setAgentMicPaused(paused) {
  isAgentMicPaused = paused;
  if (micStream) {
    micStream.getAudioTracks().forEach((track) => {
      track.enabled = !paused;
    });
  }
}

async function stopCapture() {
  isAgentMicPaused = false;
  flushWorkletBuffers();
  if (backendSocket) {
    try {
      if (backendSocket.readyState === WebSocket.OPEN) {
        backendSocket.send(JSON.stringify({ type: 'stop_session' }));
      }
    } catch (err) {
    }
    backendSocket.close();
    backendSocket = null;
  }

  currentSessionId = null;
  backendSessionReady = false;
  queuedAudioFrames = [];

  // Disconnect tab audio nodes
  if (workletCustomer) {
    workletCustomer.port.onmessage = null;
    workletCustomer.disconnect();
    workletCustomer = null;
  }
  if (workletAgent) {
    workletAgent.port.onmessage = null;
    workletAgent.disconnect();
    workletAgent = null;
  }

  if (source) {
    source.disconnect();
    source = null;
  }

  // Disconnect mic audio nodes
  if (micSource) {
    micSource.disconnect();
    micSource = null;
  }

  if (audioContext) {
    await audioContext.close();
    audioContext = null;
  }

  if (mediaStream) {
    mediaStream.getTracks().forEach((track) => track.stop());
    mediaStream = null;
  }

  if (micStream) {
    micStream.getTracks().forEach((track) => track.stop());
    micStream = null;
  }
}

function flushWorkletBuffers() {
  for (const node of [workletCustomer, workletAgent]) {
    try {
      node?.port?.postMessage({ type: 'flush' });
    } catch (err) {
    }
  }
}

function sendLeadContextToBackend(context = {}) {
  if (!backendSocket || backendSocket.readyState !== WebSocket.OPEN) {
    return;
  }

  const leadId = context.leadId || context.lead_id || null;
  const leadFacts = context.leadFacts || context.lead_facts || null;
  const leadMissingFields = context.leadMissingFields || context.lead_missing_fields || null;
  if (!leadId && !leadFacts && !leadMissingFields) {
    return;
  }

  backendSocket.send(JSON.stringify({
    type: 'lead_context',
    leadId,
    leadFacts,
    leadMissingFields,
  }));
}


function openBackendConnection(captureMode = 'gmeet', hasMicChannel = false) {
  return new Promise((resolve, reject) => {
    const socket = new WebSocket(CONFIG.BACKEND_WS_URL);
    socket.binaryType = 'arraybuffer';

    let opened = false;
    backendSessionReady = false;
    queuedAudioFrames = [];

    socket.onopen = () => {
      const params = { ...(CONFIG.OPENAI_TRANSCRIPTION_PARAMS || {}) };
      socket.send(JSON.stringify({
        type: 'start_session',
        config: {
          openaiTranscriptionParams: params,
          modelOverride: CONFIG.LLM_MODEL || null,
          captureMode,
          channels: hasMicChannel ? ['customer', 'agent'] : ['customer']
        }
      }));
      opened = true;
      resolve();
    };

    socket.onmessage = (event) => {
      try {
        const message = JSON.parse(event.data);
        handleBackendMessage(message);
      } catch (err) {
        chrome.runtime.sendMessage({
          type: 'API_ERROR',
          source: 'Backend',
          message: `Invalid backend message: ${err.message}`
        }).catch(() => {});
      }
    };

    socket.onerror = () => {
      if (!opened) {
        reject(new Error('Failed to connect to backend WebSocket'));
      }
      chrome.runtime.sendMessage({
        type: 'API_ERROR',
        source: 'Backend',
        message: 'A backend WebSocket error occurred. Verify the FastAPI server is running.'
      }).catch(() => {});
    };

    socket.onclose = (event) => {
      if (backendSocket === socket) {
        backendSocket = null;
      }
      backendSessionReady = false;
      queuedAudioFrames = [];

      if (event.code !== 1000 && event.code !== 1005) {
        chrome.runtime.sendMessage({
          type: 'API_ERROR',
          source: 'Backend',
          message: `Backend WebSocket closed unexpectedly (${event.code}).`
        }).catch(() => {});
      }
    };

    backendSocket = socket;
  });
}

function handleBackendMessage(message) {
  if (message.type === 'session_started') {
    currentSessionId = message.sessionId || null;
    backendSessionReady = true;
    flushQueuedAudioFrames();
    chrome.runtime.sendMessage({
      type: 'SESSION_READY',
      sessionId: currentSessionId
    }).catch(() => {});
    return;
  }

  if (message.type === 'transcript_update') {
    chrome.runtime.sendMessage({
      type: 'TRANSCRIPT_RECEIVED',
      transcript: message.transcript,
      isFinal: message.isFinal,
      metadata: message.metadata,
      speaker: message.speaker
    }).catch(() => {});
    return;
  }

  if (message.type === 'utterance_end') {
    chrome.runtime.sendMessage({ type: 'UTTERANCE_END' }).catch(() => {});
    return;
  }

  if (message.type === 'utterance_committed') {
    chrome.runtime.sendMessage({
      type: 'UTTERANCE_COMMITTED',
      utteranceId: message.utteranceId,
      text: message.text,
      speaker: message.speaker
    }).catch(() => {});
    return;
  }

  if (message.type === 'ai_response_chunk') {
    chrome.runtime.sendMessage({
      type: 'AI_RESPONSE_CHUNK',
      utteranceId: message.utteranceId,
      text: message.text
    }).catch(() => {});
    return;
  }

  if (message.type === 'ai_response_done') {
    chrome.runtime.sendMessage({
      type: 'AI_RESPONSE_DONE',
      utteranceId: message.utteranceId,
      fullText: message.fullText,
      badgeType: message.badgeType
    }).catch(() => {});
    return;
  }

  if (message.type === 'error') {
    chrome.runtime.sendMessage({
      type: 'API_ERROR',
      source: message.source || 'Backend',
      message: message.message || 'Unknown backend error'
    }).catch(() => {});
  }
}

async function requestSummary(requestId) {
  let summary;

  if (!currentSessionId) {
    summary = {
      extractedData: {},
      insights: ['No backend session is available for summary generation.']
    };
  } else {
    try {
      const response = await fetch(`${CONFIG.BACKEND_HTTP_URL}/api/sessions/${currentSessionId}/summary`);
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }
      summary = await response.json();
    } catch (err) {
      summary = {
        extractedData: {},
        insights: [`Failed to fetch summary from backend: ${err.message}`]
      };
    }
  }

  chrome.runtime.sendMessage({
    type: 'SUMMARY_RESULT',
    requestId,
    summary
  }).catch(() => {});
}
