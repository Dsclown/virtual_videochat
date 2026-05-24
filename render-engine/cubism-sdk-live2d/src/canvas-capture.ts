/** 从 WebGL canvas.captureStream 采样 RGB 帧。 */

function uint8ToBase64(bytes: Uint8Array): string {
  const chunk = 0x8000;
  let binary = '';
  for (let i = 0; i < bytes.length; i += chunk) {
    binary += String.fromCharCode(...bytes.subarray(i, i + chunk));
  }
  return btoa(binary);
}

export class CanvasStreamCapture {
  private _video: HTMLVideoElement;
  private _captureCanvas: HTMLCanvasElement;
  private _ctx: CanvasRenderingContext2D;
  private _stream: MediaStream | null = null;
  private _started = false;

  public constructor(private readonly _source: HTMLCanvasElement) {
    this._video = document.createElement('video');
    this._video.muted = true;
    this._video.playsInline = true;
    this._video.setAttribute('playsinline', '');
    this._captureCanvas = document.createElement('canvas');
    const ctx = this._captureCanvas.getContext('2d', { willReadFrequently: true });
    if (!ctx) {
      throw new Error('2d context unavailable');
    }
    this._ctx = ctx;
  }

  public start(fps: number): boolean {
    if (this._started) {
      return true;
    }
    try {
      const w = this._source.width;
      const h = this._source.height;
      if (w < 1 || h < 1) {
        return false;
      }
      this._captureCanvas.width = w;
      this._captureCanvas.height = h;
      const rate = Math.max(1, Math.min(60, fps));
      this._stream = this._source.captureStream(rate);
      this._video.srcObject = this._stream;
      void this._video.play();
      this._started = true;
      return true;
    } catch {
      this.stop();
      return false;
    }
  }

  public stop(): void {
    this._stream?.getTracks().forEach((t) => t.stop());
    this._stream = null;
    this._video.srcObject = null;
    this._started = false;
  }

  public get started(): boolean {
    return this._started;
  }

  public sampleRgbBase64(): { width: number; height: number; b64: string } | null {
    if (!this._started || this._video.readyState < 2) {
      return null;
    }
    const w = this._captureCanvas.width;
    const h = this._captureCanvas.height;
    this._ctx.drawImage(this._video, 0, 0, w, h);
    const img = this._ctx.getImageData(0, 0, w, h);
    const rgba = img.data;
    const rgb = new Uint8Array(w * h * 3);
    let j = 0;
    for (let i = 0; i < rgba.length; i += 4) {
      rgb[j++] = rgba[i];
      rgb[j++] = rgba[i + 1];
      rgb[j++] = rgba[i + 2];
    }
    return { width: w, height: h, b64: uint8ToBase64(rgb) };
  }
}
