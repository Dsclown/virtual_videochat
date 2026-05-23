import * as LAppDefine from './lappdefine';
import { LAppGlManager } from './lappglmanager';
import { LAppLive2DManager } from './lapplive2dmanager';
import { LAppTextureManager } from './lapptexturemanager';
import { LAppView } from './lappview';

export class LAppSubdelegate {
  public constructor() {
    this._canvas = null;
    this._glManager = new LAppGlManager();
    this._textureManager = new LAppTextureManager();
    this._live2dManager = new LAppLive2DManager();
    this._view = new LAppView();
    this._frameBuffer = null;
  }

  public release(): void {
    this._live2dManager.release();
    this._live2dManager = null;
    this._view.release();
    this._view = null;
    this._textureManager.release();
    this._textureManager = null;
    this._glManager.release();
    this._glManager = null;
  }

  public initialize(canvas: HTMLCanvasElement): boolean {
    if (!this._glManager.initialize(canvas)) {
      return false;
    }

    this._canvas = canvas;
    canvas.width = LAppDefine.CanvasSize.width;
    canvas.height = LAppDefine.CanvasSize.height;
    canvas.style.width = `${canvas.width}px`;
    canvas.style.height = `${canvas.height}px`;

    this._textureManager.setGlManager(this._glManager);

    const gl = this._glManager.getGl();
    if (!this._frameBuffer) {
      this._frameBuffer = gl.getParameter(gl.FRAMEBUFFER_BINDING);
    }

    gl.enable(gl.BLEND);
    gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);

    this._view.initialize(this);
    this._live2dManager.setOffscreenSize(canvas.width, canvas.height);
    this._view.initializeSprite();
    this._live2dManager.initialize(this);

    gl.viewport(0, 0, canvas.width, canvas.height);
    return true;
  }

  public update(): void {
    if (this._glManager.getGl().isContextLost()) {
      return;
    }

    const gl = this._glManager.getGl();
    gl.clearColor(26 / 255, 29 / 255, 39 / 255, 1.0);
    gl.enable(gl.DEPTH_TEST);
    gl.depthFunc(gl.LEQUAL);
    gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
    gl.clearDepth(1.0);
    gl.enable(gl.BLEND);
    gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);
    this._view.render();
  }

  public createShader(): WebGLProgram {
    const gl = this._glManager.getGl();
    const vertexShaderId = gl.createShader(gl.VERTEX_SHADER);
    const vertexShader =
      'precision mediump float;' +
      'attribute vec3 position;' +
      'attribute vec2 uv;' +
      'varying vec2 vuv;' +
      'void main(void)' +
      '{' +
      '   gl_Position = vec4(position, 1.0);' +
      '   vuv = uv;' +
      '}';
    gl.shaderSource(vertexShaderId, vertexShader);
    gl.compileShader(vertexShaderId);

    const fragmentShaderId = gl.createShader(gl.FRAGMENT_SHADER);
    const fragmentShader =
      'precision mediump float;' +
      'varying vec2 vuv;' +
      'uniform sampler2D texture;' +
      'void main(void)' +
      '{' +
      '   gl_FragColor = texture2D(texture, vuv);' +
      '}';
    gl.shaderSource(fragmentShaderId, fragmentShader);
    gl.compileShader(fragmentShaderId);

    const programId = gl.createProgram();
    gl.attachShader(programId, vertexShaderId);
    gl.attachShader(programId, fragmentShaderId);
    gl.deleteShader(vertexShaderId);
    gl.deleteShader(fragmentShaderId);
    gl.linkProgram(programId);
    gl.useProgram(programId);
    return programId;
  }

  public getTextureManager(): LAppTextureManager {
    return this._textureManager;
  }

  public getFrameBuffer(): WebGLFramebuffer {
    return this._frameBuffer;
  }

  public getCanvas(): HTMLCanvasElement {
    return this._canvas;
  }

  public getGlManager(): LAppGlManager {
    return this._glManager;
  }

  public getGl(): WebGLRenderingContext | WebGL2RenderingContext {
    return this._glManager.getGl();
  }

  public getLive2DManager(): LAppLive2DManager {
    return this._live2dManager;
  }

  public isContextLost(): boolean {
    return this._glManager.getGl().isContextLost();
  }

  private _canvas: HTMLCanvasElement;
  private _view: LAppView;
  private _textureManager: LAppTextureManager;
  private _frameBuffer: WebGLFramebuffer;
  private _glManager: LAppGlManager;
  private _live2dManager: LAppLive2DManager;
}
