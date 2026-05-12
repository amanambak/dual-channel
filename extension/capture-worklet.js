/**
 * AudioWorkletProcessor to convert Float32 PCM to Int16 PCM.
 */
class CaptureWorklet extends AudioWorkletProcessor {
  constructor() {
    super();
    this.chunkSampleCount = Math.round(sampleRate * 0.025);
    this.pendingSamples = new Float32Array(this.chunkSampleCount);
    this.pendingSampleCount = 0;
    this.port.onmessage = (event) => {
      if (event.data?.type === 'flush') {
        this.flushPendingSamples();
      }
    };
  }

  process(inputs, outputs, parameters) {
    const input = inputs[0];
    if (input.length > 0) {
      this.enqueueMonoSamples(this.mixToMono(input));
    }

    // Returning true tells the browser to keep this processor alive
    return true;
  }

  mixToMono(input) {
    if (input.length === 1) {
      return input[0];
    }

    const sampleCount = input[0].length;
    const mixed = new Float32Array(sampleCount);
    for (let channelIndex = 0; channelIndex < input.length; channelIndex += 1) {
      const channel = input[channelIndex];
      for (let sampleIndex = 0; sampleIndex < sampleCount; sampleIndex += 1) {
        mixed[sampleIndex] += channel[sampleIndex] / input.length;
      }
    }
    return mixed;
  }

  enqueueMonoSamples(inputChannel) {
    let offset = 0;
    while (offset < inputChannel.length) {
      const writable = Math.min(
        this.chunkSampleCount - this.pendingSampleCount,
        inputChannel.length - offset
      );
      this.pendingSamples.set(
        inputChannel.subarray(offset, offset + writable),
        this.pendingSampleCount
      );
      this.pendingSampleCount += writable;
      offset += writable;

      if (this.pendingSampleCount === this.chunkSampleCount) {
        const int16Buffer = this.float32ToInt16(this.pendingSamples);
        this.port.postMessage(int16Buffer.buffer, [int16Buffer.buffer]);
        this.pendingSamples = new Float32Array(this.chunkSampleCount);
        this.pendingSampleCount = 0;
      }
    }
  }

  flushPendingSamples() {
    if (this.pendingSampleCount <= 0) {
      return;
    }
    const int16Buffer = this.float32ToInt16(
      this.pendingSamples.subarray(0, this.pendingSampleCount)
    );
    this.port.postMessage(int16Buffer.buffer, [int16Buffer.buffer]);
    this.pendingSamples = new Float32Array(this.chunkSampleCount);
    this.pendingSampleCount = 0;
  }

  /**
   * Converts Float32Array to Int16Array (PCM).
   * @param {Float32Array} float32Array
   * @returns {Int16Array}
   */
  float32ToInt16(float32Array) {
    const length = float32Array.length;
    const int16Array = new Int16Array(length);
    for (let i = 0; i < length; i += 1) {
      let sample = float32Array[i];
      if (sample > 1) {
        sample = 1;
      } else if (sample < -1) {
        sample = -1;
      }
      int16Array[i] = sample < 0 ? sample * 0x8000 : sample * 0x7fff;
    }
    return int16Array;
  }
}

registerProcessor('capture-worklet', CaptureWorklet);
