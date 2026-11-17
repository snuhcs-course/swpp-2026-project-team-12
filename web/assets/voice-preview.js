// Public, pre-generated samples stay in memory for this page session only.
export class VoicePreview {
  constructor({ load, play, stop, status, current }) {
    Object.assign(this, { load, play, stop, status, current });
    this.cache = new Map(); this.generation = 0;
  }
  sample(key) {
    if (!this.cache.has(key)) {
      const pending = Promise.resolve().then(() => this.load(key)).catch(error => {
        if (this.cache.get(key) === pending) this.cache.delete(key);
        throw error;
      });
      this.cache.set(key, pending);
    }
    return this.cache.get(key);
  }
  preload(key) { this.sample(key).catch(() => {}); }
  cancel() { this.generation++; this.stop(); this.status(''); }
  async preview(key) {
    this.cancel();
    const generation = this.generation;
    const active = () => generation === this.generation && this.current(key);
    this.status('목소리 예시를 준비하고 있어요.');
    try {
      const blob = await this.sample(key);
      if (!active()) return;
      this.status('목소리 예시를 듣고 있어요.');
      await this.play(blob, () => { if (active()) this.status(''); });
    } catch {
      if (active()) { this.stop(); this.status('재생하지 못했어요. 미리 듣기를 다시 눌러 주세요.'); }
    }
  }
}
