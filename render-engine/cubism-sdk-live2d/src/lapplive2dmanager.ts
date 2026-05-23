import { CubismMatrix44 } from '@framework/math/cubismmatrix44';
import { CubismWebGLOffscreenManager } from '@framework/rendering/cubismoffscreenmanager';

import * as LAppDefine from './lappdefine';
import { LAppModel } from './lappmodel';
import { LAppSubdelegate } from './lappsubdelegate';

export class LAppLive2DManager {
  public constructor() {
    this._subdelegate = null;
    this._viewMatrix = new CubismMatrix44();
    this._models = new Array<LAppModel>();
  }

  public release(): void {
    this._models.length = 0;
  }

  public setOffscreenSize(width: number, height: number): void {
    for (let i = 0; i < this._models.length; i++) {
      this._models[i]?.setRenderTargetSize(width, height);
    }
  }

  public onUpdate(): void {
    const gl = this._subdelegate.getGl();
    CubismWebGLOffscreenManager.getInstance().beginFrameProcess(gl);

    const { width, height } = this._subdelegate.getCanvas();
    const projection: CubismMatrix44 = new CubismMatrix44();
    const model: LAppModel = this._models[0];

    if (model?.getModel()) {
      if (model.getModel().getCanvasWidth() > 1.0 && width < height) {
        model.getModelMatrix().setWidth(2.0);
        projection.scale(1.0, width / height);
      } else {
        projection.scale(height / width, 1.0);
      }

      if (this._viewMatrix != null) {
        projection.multiplyByMatrix(this._viewMatrix);
      }
    }

    model?.update();
    model?.draw(projection);

    CubismWebGLOffscreenManager.getInstance().endFrameProcess(gl);
    CubismWebGLOffscreenManager.getInstance().releaseStaleRenderTextures(gl);
  }

  public loadModelFromUrl(model3Url: string): void {
    const normalized = model3Url.split('?')[0];
    const slash = normalized.lastIndexOf('/');
    const dir = normalized.substring(0, slash + 1);
    const fileName = normalized.substring(slash + 1);

    this._models.length = 0;
    const instance = new LAppModel();
    instance.setSubdelegate(this._subdelegate);
    instance.loadAssets(dir, fileName);
    this._models.push(instance);
  }

  public getModel(): LAppModel | null {
    return this._models[0] ?? null;
  }

  public setViewMatrix(m: CubismMatrix44): void {
    for (let i = 0; i < 16; i++) {
      this._viewMatrix.getArray()[i] = m.getArray()[i];
    }
  }

  public initialize(subdelegate: LAppSubdelegate): void {
    this._subdelegate = subdelegate;
    this.loadModelFromUrl(LAppDefine.ModelUrl);
  }

  private _subdelegate: LAppSubdelegate;
  _viewMatrix: CubismMatrix44;
  _models: Array<LAppModel>;
}
