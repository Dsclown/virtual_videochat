import { CubismFramework, Option } from '@framework/live2dcubismframework';
import { CubismLogError } from '@framework/utils/cubismdebug';

import * as LAppDefine from './lappdefine';
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

  public tick(): void {
    if (!this._subdelegate) {
      return;
    }
    LAppPal.updateTime();
    this._subdelegate.update();
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
}

declare global {
  interface Window {
    __avatar?: {
      isReady(): boolean;
      setMouth(value: number): void;
      renderTick(): void;
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
    renderTick(): void {
      delegate.tick();
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
