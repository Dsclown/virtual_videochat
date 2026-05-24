import { CubismMatrix44 } from '@framework/math/cubismmatrix44';
import { CubismViewMatrix } from '@framework/math/cubismviewmatrix';

import * as LAppDefine from './lappdefine';
import { LAppSubdelegate } from './lappsubdelegate';

export class LAppView {
  public constructor() {
    this._programId = null;
    this._deviceToScreen = new CubismMatrix44();
    this._viewMatrix = new CubismViewMatrix();
  }

  public initialize(subdelegate: LAppSubdelegate): void {
    this._subdelegate = subdelegate;
    const { width, height } = subdelegate.getCanvas();

    const ratio: number = width / height;
    const left: number = -ratio;
    const right: number = ratio;
    const bottom: number = LAppDefine.ViewLogicalLeft;
    const top: number = LAppDefine.ViewLogicalRight;

    this._viewMatrix.setScreenRect(left, right, bottom, top);
    this._viewMatrix.scale(
      LAppDefine.ViewScale * LAppDefine.ViewScaleFactor,
      LAppDefine.ViewScale * LAppDefine.ViewScaleFactor
    );

    this._deviceToScreen.loadIdentity();
    if (width > height) {
      const screenW: number = Math.abs(right - left);
      this._deviceToScreen.scaleRelative(screenW / width, -screenW / width);
    } else {
      const screenH: number = Math.abs(top - bottom);
      this._deviceToScreen.scaleRelative(screenH / height, -screenH / height);
    }
    this._deviceToScreen.translateRelative(-width * 0.5, -height * 0.5);

    this._viewMatrix.setMaxScale(LAppDefine.ViewMaxScale);
    this._viewMatrix.setMinScale(LAppDefine.ViewMinScale);
    this._viewMatrix.setMaxScreenRect(
      LAppDefine.ViewLogicalMaxLeft,
      LAppDefine.ViewLogicalMaxRight,
      LAppDefine.ViewLogicalMaxBottom,
      LAppDefine.ViewLogicalMaxTop
    );
  }

  public release(): void {
    this._viewMatrix = null;
    this._deviceToScreen = null;
    if (this._programId) {
      this._subdelegate.getGlManager().getGl().deleteProgram(this._programId);
      this._programId = null;
    }
  }

  public render(): void {
    if (this._programId) {
      this._subdelegate.getGlManager().getGl().useProgram(this._programId);
    }

    const lapplive2dmanager = this._subdelegate.getLive2DManager();
    if (lapplive2dmanager != null) {
      lapplive2dmanager.setViewMatrix(this._viewMatrix);
      lapplive2dmanager.onUpdate();
    }
  }

  public initializeSprite(): void {
    if (this._programId == null) {
      this._programId = this._subdelegate.createShader();
    }
  }

  _deviceToScreen: CubismMatrix44;
  _viewMatrix: CubismViewMatrix;
  _programId: WebGLProgram;
  private _subdelegate: LAppSubdelegate;
}
