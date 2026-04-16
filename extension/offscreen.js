// offscreen.js — Offscreen document
// Owns tab audio capture and the persistent backend WebSocket session.

let audioContext;
let mediaStream;
let micStream;
let source;
let micSource;
let merger;
let workletNode;
let backendSocket;
let currentSessionId = null;
let pcmBuffer = [];
let sendInterval = null;

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

    // Create the merger gain node
    merger = audioContext.createGain();

    // Tab audio source
    source = audioContext.createMediaStreamSource(mediaStream);
    // Gain node for tab audio to control monitoring volume and feed to merger
    const tabGain = audioContext.createGain();
    source.connect(tabGain);
    // Tab audio to local playback (for monitoring)
    tabGain.connect(audioContext.destination);
    // Tab audio to merger (for sending to backend)
    tabGain.connect(merger);

    // Try to add microphone with echo cancellation and noise suppression
    try {
      micStream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true
        }
      });
      micSource = audioContext.createMediaStreamSource(micStream);
      // Gain node for mic audio (we don't want to monitor mic locally to avoid echo)
      const micGain = audioContext.createGain();
      micSource.connect(micGain);
      // Mic audio only to merger (not to local playback)
      micGain.connect(merger);
    } catch (micErr) {
      console.warn('Microphone access denied or constraints not supported, continuing with tab audio only:', micErr.message);
      micStream = null;
      micSource = null;
    }

    await openBackendConnection();
    await setupWorklet();
  } catch (err) {
    chrome.runtime.sendMessage({
      type: 'API_ERROR',
      source: 'Offscreen',
      message: `Failed to start audio capture: ${err.message}`
    }).catch(() => {});
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

  if (workletNode) {
    workletNode.disconnect();
    workletNode = null;
  }

  if (sendInterval) {
    clearInterval(sendInterval);
    sendInterval = null;
  }

  // Disconnect tab audio nodes
  if (source) {
    source.disconnect();
    source = null;
  }
  if (tabGain) {
    tabGain.disconnect();
    tabGain = null;
  }

  // Disconnect mic audio nodes
  if (micSource) {
    micSource.disconnect();
    micSource = null;
  }
  if (micGain) {
    micGain.disconnect();
    micGain = null;
  }

  if (merger) {
    merger.disconnect();
    merger = null;
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

async function setupWorklet() {
  await audioContext.audioWorklet.addModule('capture-worklet.js');
  workletNode = new AudioWorkletNode(audioContext, 'capture-worklet');

  sendInterval = setInterval(() => {
    if (pcmBuffer.length > 0 && backendSocket && backendSocket.readyState === WebSocket.OPEN) {
      const totalLength = pcmBuffer.reduce((sum, buf) => sum + buf.byteLength, 0);
      const combined = new Uint8Array(totalLength);
      let offset = 0;
      for (const buf of pcmBuffer) {
        combined.set(new Uint8Array(buf), offset);
        offset += buf.byteLength;
      }
      backendSocket.send(combined.buffer);
      pcmBuffer = [];
    }
  }, 100);

  workletNode.port.onmessage = (event) => {
    pcmBuffer.push(event.data);
  };

  merger.connect(workletNode);
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
      socket.send(JSON.stringify({
        type: 'start_session',
        config: {
          deepgramParams: params,
          geminiModel: CONFIG.GEMINI_MODEL || null
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
