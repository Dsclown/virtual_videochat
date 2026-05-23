from vtuber.config.loader import AvatarConfig
from vtuber.modules.avatar.base import AvatarModule
from vtuber.modules.avatar.live2d import Live2DAvatar


class AvatarFactory:
    @staticmethod
    def create(cfg: AvatarConfig) -> AvatarModule:
        # JSON 解析仍用 Live2DAvatar；Playwright 渲染由 PlaywrightManager 负责
        if cfg.provider not in ("live2d", "playwright"):
            raise ValueError(
                f"avatar.provider 仅支持 live2d / playwright，当前: {cfg.provider}"
            )
        return Live2DAvatar()
