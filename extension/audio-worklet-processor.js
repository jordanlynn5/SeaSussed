// extension/audio-worklet-processor.js
// AudioWorklet processor — runs in audio rendering thread.
// Must be a standalone file (no imports, no ES modules).

class PcmProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.bufferSize = 1600; // 100ms @ 16kHz
    this.buffer = new Int16Array(this.bufferSize);
    this.bufferIndex = 0;
  }

  process(inputs, outputs, parameters) {
    if (!inputs[0] || !inputs[0][0]) {
      return true;
    }

    const channel = inputs[0][0]; // Float32Array, one channel

    for (let i = 0; i < channel.length; i++) {
      // Clamp and convert Float32 [-1.0, 1.0] → Int16 [-32768, 32767]
      const clamped = Math.max(-1.0, Math.min(1.0, channel[i]));
      const int16Sample = Math.round(clamped * 32767);
      this.buffer[this.bufferIndex] = int16Sample;
      this.bufferIndex++;

      if (this.bufferIndex >= this.bufferSize) {
        // Transfer buffer (zero-copy) then reset
        const chunk = new Int16Array(this.buffer);
        this.port.postMessage(chunk.buffer, [chunk.buffer]);
        this.buffer = new Int16Array(this.bufferSize);
        this.bufferIndex = 0;
      }
    }

    return true; // keep processor alive
  }
}

registerProcessor('pcm-processor', PcmProcessor);
