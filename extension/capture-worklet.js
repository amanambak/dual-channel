/**
 * AudioWorkletProcessor to convert Float32 PCM to Int16 PCM.
 */
class CaptureWorklet extends AudioWorkletProcessor {
  constructor() {
    super();
  }

  process(inputs, outputs, parameters) {
    const input = inputs[0];
    if (input.length > 0) {
      // Mono conversion (taking the first channel)
      const inputChannel = input[0];

      // Convert to Int16 PCM
      const int16Buffer = this.float32ToInt16(inputChannel);

      // Send to main thread
      this.port.postMessage(int16Buffer.buffer, [int16Buffer.buffer]);
    }

    // Returning true tells the browser to keep this processor alive
    return true;
  }

  /**
   * Converts Float32Array to Int16Array (PCM).
   * @param {Float32Array} float32Array
   * @returns {Int16Array}
   */
  float32ToInt16(float32Array) {
    let i = float32Array.length;
    const int16Array = new Int16Array(i);
    while (i--) {
      // Clamp the value to [-1, 1]
      let s = Math.max(-1, Math.min(1, float32Array[i]));
      // Convert to signed 16-bit integer
      int16Array[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
    }
    return int16Array;
  }
}

registerProcessor('capture-worklet', CaptureWorklet);
