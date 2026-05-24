import { CubismFramework, Option } from '@framework/live2dcubismframework';
import { InvalidMotionQueueEntryHandleValue } from '@framework/motion/cubismmotionqueuemanager';
import { CubismLogError } from '@framework/utils/cubismdebug';

import * as LAppDefine from './lappdefine';
import { CanvasStreamCapture } from './canvas-capture';
import { LAppPal } from './lapppal';
import { LAppSubdelegate } from './lappsubdelegate';

let s_instance: AvatarDelegate | null = null;

export class AvatarDelegate {
  public static getInstance(): AvatarDelegate {
    if (s_instance == null) {
      s_instance = new AvatarDelegate();
    }
    return s_instance;
  }

  public static releaseInstance(): void {
    if (s_instance != null) {
      s_instance.release();
    }
    s_instance = null;
  }

  public initialize(): boolean {
    this.initializeCubism();
    return this.initializeSubdelegate();
  }

  public isModelReady(): boolean {
    const model = this._subdelegate?.getLive2DManager()?.getModel();
    return !!model?.isLoadComplete();
  }

  public setMouth(value: number): void {
    this._subdelegate?.getLive2DManager()?.getModel()?.setMouthOpenY(value);
  }

  /** LLM / 服务端驱动：表情索引（有 Expressions 的模型）或动作组名 */
  public applyAction(spec: {
    expressionIndex?: number;
    motionGroup?: string;
  }): boolean {
    const model = this._subdelegate?.getLive2DManager()?.getModel();
    if (!model) {
      return false;
    }
    if (spec.motionGroup) {
      model.startRandomMotion(spec.motionGroup, LAppDefine.PriorityNormal);
      return true;
    }
    if (spec.expressionIndex != null) {
      model.setExpressionByIndex(spec.expressionIndex);
      return true;
    }
    return false;
  }

  public startRandomMotion(group: string): boolean {
    const model = this._subdelegate?.getLive2DManager()?.getModel();
    if (!model) {
      return false;
    }
    const handle = model.startRandomMotion(group, LAppDefine.PriorityNormal);
    return handle !== InvalidMotionQueueEntryHandleValue;
  }

  public tick(): void {
    if (!this._subdelegate) {
      return;
    }
    LAppPal.updateTime();
    this._subdelegate.update();
  }

  public getSourceCanvas(): HTMLCanvasElement | null {
    return this._subdelegate?.getCanvas() ?? null;
  }

  public startCaptureStream(fps: number): boolean {
    const canvas = this.getSourceCanvas();
    if (!canvas) {
      return false;
    }
    if (!this._capture) {
      this._capture = new CanvasStreamCapture(canvas);
    }
    return this._capture.start(fps);
  }

  public stopCaptureStream(): void {
    this._capture?.stop();
    this._capture = null;
  }

  public captureFrameRgb(): { width: number; height: number; b64: string } | null {
    this.tick();
    return this._capture?.sampleRgbBase64() ?? null;
  }

  public getDiagnostics(): Record<string, unknown> {
    const model = this._subdelegate?.getLive2DManager()?.getModel();
    const core = model?.getModel();
    let drawables = 0;
    let visible = 0;
    if (core?.getDrawableCount) {
      drawables = core.getDrawableCount();
      for (let i = 0; i < drawables; i++) {
        if (core.getDrawableDynamicFlagIsVisible(i)) {
          visible += 1;
        }
      }
    }
    return {
      ready: this.isModelReady(),
      captureStream: this._capture?.started ?? false,
      drawables,
      visible,
      modelUrl: LAppDefine.ModelUrl,
      size: {
        w: LAppDefine.RenderWidth,
        h: LAppDefine.RenderHeight,
      },
    };
  }

  private initializeCubism(): void {
    LAppPal.updateTime();
    this._cubismOption.logFunction = LAppPal.printMessage;
    this._cubismOption.loggingLevel = LAppDefine.CubismLoggingLevel;
    CubismFramework.startUp(this._cubismOption);
    CubismFramework.initialize();
  }

  private initializeSubdelegate(): boolean {
    const stage = document.getElementById('stage') ?? document.body;
    const canvas = document.createElement('canvas');
    canvas.id = 'live2d-canvas';
    stage.appendChild(canvas);

    this._subdelegate = new LAppSubdelegate();
    const ok = this._subdelegate.initialize(canvas);
    if (!ok || this._subdelegate.isContextLost()) {
      CubismLogError('WebGL context initialization failed.');
      return false;
    }
    return true;
  }

  private release(): void {
    this.stopCaptureStream();
    this._subdelegate?.release();
    this._subdelegate = null;
    CubismFramework.dispose();
    this._cubismOption = null;
  }

  private constructor() {
    this._cubismOption = new Option();
  }

  private _cubismOption: Option;
  private _subdelegate: LAppSubdelegate;
  private _capture: CanvasStreamCapture | null = null;
}

declare global {
  interface Window {
    __avatar?: {
      isReady(): boolean;
      setMouth(value: number): void;
      applyAction(spec: {
        expressionIndex?: number;
        motionGroup?: string;
      }): boolean;
      startRandomMotion(group: string): boolean;
      renderTick(): void;
      startCaptureStream(fps: number): boolean;
      stopCaptureStream(): void;
      captureFrameRgb(): { width: number; height: number; b64: string } | null;
      getDiagnostics(): Record<string, unknown>;
    };
  }
}

export function mountAvatarBridge(): void {
  const delegate = AvatarDelegate.getInstance();
  const statusEl = document.getElementById('status');

  window.__avatar = {
    isReady(): boolean {
      return delegate.isModelReady();
    },
    setMouth(value: number): void {
      delegate.setMouth(value);
    },
    applyAction(spec: {
      expressionIndex?: number;
      motionGroup?: string;
    }): boolean {
      requestAnimationFrame(() => {
        delegate.applyAction(spec);
      });
      return true;
    },
    startRandomMotion(group: string): boolean {
      requestAnimationFrame(() => {
        delegate.startRandomMotion(group);
      });
      return true;
    },
    renderTick(): void {
      delegate.tick();
    },
    startCaptureStream(fps: number): boolean {
      return delegate.startCaptureStream(fps);
    },
    stopCaptureStream(): void {
      delegate.stopCaptureStream();
    },
    captureFrameRgb(): { width: number; height: number; b64: string } | null {
      return delegate.captureFrameRgb();
    },
    getDiagnostics(): Record<string, unknown> {
      return delegate.getDiagnostics();
    },
  };

  if (!delegate.initialize()) {
    if (statusEl) {
      statusEl.textContent = 'error: WebGL init failed';
    }
    return;
  }

  const warm = (): void => {
    delegate.tick();
    if (delegate.isModelReady()) {
      if (statusEl) {
        statusEl.textContent = 'ready';
      }
      return;
    }
    requestAnimationFrame(warm);
  };
  warm();
}
