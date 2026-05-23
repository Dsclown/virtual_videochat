import { LogLevel } from '@framework/live2dcubismframework';

export let RenderWidth = 480;
export let RenderHeight = 480;
export let ModelUrl =
  '/live2d-models/shizuku/runtime/shizuku.model3.json';
export let ViewScaleFactor = 1.0;

export function configureFromUrl(): void {
  const params = new URLSearchParams(location.search);
  RenderWidth = Number(params.get('w') || 480);
  RenderHeight = Number(params.get('h') || 480);
  ModelUrl =
    params.get('model') ||
    '/live2d-models/shizuku/runtime/shizuku.model3.json';
  const scale = Number(params.get('scale') || 0);
  if (scale > 0) {
    ViewScaleFactor = scale;
  }
}

export const CanvasSize: { width: number; height: number } = {
  get width() {
    return RenderWidth;
  },
  get height() {
    return RenderHeight;
  },
};

export const CanvasNum = 1;

export const ViewScale = 1.0;
export const ViewMaxScale = 2.0;
export const ViewMinScale = 0.8;

export const ViewLogicalLeft = -1.0;
export const ViewLogicalRight = 1.0;
export const ViewLogicalBottom = -1.0;
export const ViewLogicalTop = 1.0;

export const ViewLogicalMaxLeft = -2.0;
export const ViewLogicalMaxRight = 2.0;
export const ViewLogicalMaxBottom = -2.0;
export const ViewLogicalMaxTop = 2.0;

export const ShaderPath = 'Framework/Shaders/WebGL/';

export const MotionGroupIdle = 'Idle';
export const MotionGroupTapBody = 'TapBody';

export const HitAreaNameHead = 'Head';
export const HitAreaNameBody = 'Body';

export const PriorityNone = 0;
export const PriorityIdle = 1;
export const PriorityNormal = 2;
export const PriorityForce = 3;

export const MOCConsistencyValidationEnable = true;
export const MotionConsistencyValidationEnable = true;

export const DebugLogEnable = false;
export const DebugTouchLogEnable = false;

export const CubismLoggingLevel: LogLevel = LogLevel.LogLevel_Warning;

export const RenderTargetWidth = 1900;
export const RenderTargetHeight = 1000;
