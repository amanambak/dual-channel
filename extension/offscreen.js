// offscreen.js — Offscreen document
// Owns tab audio capture and the persistent backend WebSocket session.
// Supports dual-channel: tab audio (customer) + microphone (agent)

let audioContext;
let mediaStream;
let micStream;
let source;
let micSource;
let backendSocket;
let currentSessionId = null;
let sendIntervalCustomer = null;
let sendIntervalAgent = null;
let isAgentMicPaused = false;

chrome.runtime.onMessage.addListener((message) => {
  if (message.type === 'START_CAPTURE' && message.offscreen) {
    startCapture(message.streamId, message.captureMode);
  } else if (message.type === 'STOP_CAPTURE' && message.offscreen) {
    stopCapture();
  } else if (message.type === 'SET_AGENT_MIC_PAUSED' && message.offscreen) {
    setAgentMicPaused(Boolean(message.paused));
  } else if (message.type === 'REQUEST_SUMMARY' && message.offscreen) {
    requestSummary(message.requestId);
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
      sampleRate: 16000
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
            echoCancellation: true,
            noiseSuppression: true,
            autoGainControl: true
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

    await openBackendConnection(captureMode, hasMicChannel);
    await setupDualChannelWorklets(tabGain, hasMicChannel ? micGain : null);

  } catch (err) {
    chrome.runtime.sendMessage({
      type: 'API_ERROR',
      source: 'Offscreen',
      message: `Failed to start audio capture: ${err.message}`
    }).catch(() => {});
  }
}

/**
 * Creates a periodic interval that drains an audio buffer and sends it over
 * the backend WebSocket with a single-byte channel prefix.
 *
 * @param {number} channelByte - 0 = customer, 1 = agent
 * @param {Array}  buffer      - Shared buffer array (mutated in-place)
 * @param {number} intervalMs  - Polling interval in milliseconds
 * @returns {number} The interval ID (pass to clearInterval to stop it)
 */
function createChannelSender(channelByte, buffer, intervalMs = 100, shouldSkip = () => false) {
  return setInterval(() => {
    if (shouldSkip()) {
      buffer.length = 0;
      return;
    }
    if (buffer.length === 0 || !backendSocket || backendSocket.readyState !== WebSocket.OPEN) {
      return;
    }
    const totalLength = buffer.reduce((sum, buf) => sum + buf.byteLength, 0);
    if (totalLength === 0) {
      return;
    }
    const combined = new Uint8Array(totalLength);
    let offset = 0;
    for (const buf of buffer) {
      combined.set(new Uint8Array(buf), offset);
      offset += buf.byteLength;
    }
    const channelBuffer = new ArrayBuffer(totalLength + 1);
    const view = new Uint8Array(channelBuffer);
    view[0] = channelByte;
    view.set(combined, 1);
    backendSocket.send(channelBuffer);
    buffer.length = 0; // drain in-place
  }, intervalMs);
}

async function setupDualChannelWorklets(tabGain, micGain) {
  // Worklet for tab audio (channel 0 - customer)
  await audioContext.audioWorklet.addModule('capture-worklet.js');

  const workletCustomer = new AudioWorkletNode(audioContext, 'capture-worklet');
  tabGain.connect(workletCustomer);
  const bufferCustomer = [];
  workletCustomer.port.onmessage = (event) => { bufferCustomer.push(event.data); };
  sendIntervalCustomer = createChannelSender(0, bufferCustomer);

  // Worklet for microphone (channel 1 - agent)
  if (micGain) {
    const workletAgent = new AudioWorkletNode(audioContext, 'capture-worklet');
    micGain.connect(workletAgent);
    const bufferAgent = [];
    workletAgent.port.onmessage = (event) => { bufferAgent.push(event.data); };
    sendIntervalAgent = createChannelSender(1, bufferAgent, 100, () => isAgentMicPaused);
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
  if (sendIntervalCustomer) {
    clearInterval(sendIntervalCustomer);
    sendIntervalCustomer = null;
  }
  if (sendIntervalAgent) {
    clearInterval(sendIntervalAgent);
    sendIntervalAgent = null;
  }

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

  // Disconnect tab audio nodes
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

function openBackendConnection(captureMode = 'gmeet', hasMicChannel = false) {
  return new Promise((resolve, reject) => {
    const socket = new WebSocket(CONFIG.BACKEND_WS_URL);
    socket.binaryType = 'arraybuffer';

    let opened = false;

    socket.onopen = () => {
      const params = CONFIG.DEEPGRAM_PARAMS || {};
      params.diarize = params.diarize || 'true';
      params.diarize_version = params.diarize_version || '2023-03-31';
      params.multichannel = hasMicChannel ? 'true' : 'false';
      socket.send(JSON.stringify({
        type: 'start_session',
        config: {
          deepgramParams: params,
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
