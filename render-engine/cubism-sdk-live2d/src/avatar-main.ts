import { configureFromUrl } from './lappdefine';
import { mountAvatarBridge } from './avatar-delegate';

configureFromUrl();

window.addEventListener(
  'load',
  (): void => {
    mountAvatarBridge();
  },
  { passive: true }
);

window.addEventListener(
  'beforeunload',
  (): void => {
    import('./avatar-delegate').then(({ AvatarDelegate }) => {
      AvatarDelegate.releaseInstance();
    });
  },
  { passive: true }
);
