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

chrome.runtime.onMessage.addListener((message) => {
  if (message.type === 'START_CAPTURE' && message.offscreen) {
    startCapture(message.streamId);
  } else if (message.type === 'STOP_CAPTURE' && message.offscreen) {
    stopCapture();
  } else if (message.type === 'REQUEST_SUMMARY' && message.offscreen) {
    requestSummary(message.requestId);
  }
});

async function startCapture(streamId) {
  try {
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
      // NOTE: Do NOT connect micGain to audioContext.destination to avoid echo
    } catch (micErr) {
      console.warn('Microphone access denied:', micErr.message);
      micStream = null;
      micSource = null;
    }

    await openBackendConnection();
    await setupDualChannelWorklets(tabGain, micGain);

  } catch (err) {
    chrome.runtime.sendMessage({
      type: 'API_ERROR',
      source: 'Offscreen',
      message: `Failed to start audio capture: ${err.message}`
    }).catch(() => {});
  }
}

async function setupDualChannelWorklets(tabGain, micGain) {
  // Worklet for tab audio (channel 0 - customer)
  await audioContext.audioWorklet.addModule('capture-worklet.js');
  const workletCustomer = new AudioWorkletNode(audioContext, 'capture-worklet');
  tabGain.connect(workletCustomer);

  const bufferCustomer = [];
  workletCustomer.port.onmessage = (event) => {
    bufferCustomer.push(event.data);
  };

  // Send interval for customer channel (every 100ms)
  const sendIntervalCustomer = setInterval(() => {
    if (bufferCustomer.length > 0 && backendSocket && backendSocket.readyState === WebSocket.OPEN) {
      const totalLength = bufferCustomer.reduce((sum, buf) => sum + buf.byteLength, 0);
      if (totalLength > 0) {
        const combined = new Uint8Array(totalLength);
        let offset = 0;
        for (const buf of bufferCustomer) {
          combined.set(new Uint8Array(buf), offset);
          offset += buf.byteLength;
        }
        // Send customer channel audio with prefix
        const channelBuffer = new ArrayBuffer(totalLength + 1);
        const view = new Uint8Array(channelBuffer);
        view[0] = 0; // Channel 0 = customer
        view.set(combined, 1);
        backendSocket.send(channelBuffer);
        bufferCustomer.length = 0;
      }
    }
  }, 100);

  // Worklet for microphone (channel 1 - agent)
  if (micGain) {
    const workletAgent = new AudioWorkletNode(audioContext, 'capture-worklet');
    micGain.connect(workletAgent);

    const bufferAgent = [];
    workletAgent.port.onmessage = (event) => {
      bufferAgent.push(event.data);
    };

    // Send interval for agent channel (every 100ms)
    const sendIntervalAgent = setInterval(() => {
      if (bufferAgent.length > 0 && backendSocket && backendSocket.readyState === WebSocket.OPEN) {
        const totalLength = bufferAgent.reduce((sum, buf) => sum + buf.byteLength, 0);
        if (totalLength > 0) {
          const combined = new Uint8Array(totalLength);
          let offset = 0;
          for (const buf of bufferAgent) {
            combined.set(new Uint8Array(buf), offset);
            offset += buf.byteLength;
          }
          // Send agent channel audio with prefix
          const channelBuffer = new ArrayBuffer(totalLength + 1);
          const view = new Uint8Array(channelBuffer);
          view[0] = 1; // Channel 1 = agent
          view.set(combined, 1);
          backendSocket.send(channelBuffer);
          bufferAgent.length = 0;
        }
      }
    }, 100);
  }
}

async function stopCapture() {
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

function openBackendConnection() {
  return new Promise((resolve, reject) => {
    const socket = new WebSocket(CONFIG.BACKEND_WS_URL);
    socket.binaryType = 'arraybuffer';

    let opened = false;

    socket.onopen = () => {
      const params = CONFIG.DEEPGRAM_PARAMS || {};
      params.diarize = params.diarize || 'true';
      params.diarize_version = params.diarize_version || '2023-03-31';
      // Enable multichannel for dual-channel support
      params.multichannel = 'true';
      socket.send(JSON.stringify({
        type: 'start_session',
        config: {
          deepgramParams: params,
          geminiModel: CONFIG.GEMINI_MODEL || null,
          channels: ['customer', 'agent']
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
      metadata: message.metadata
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
      text: message.text
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