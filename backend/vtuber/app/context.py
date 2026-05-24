import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor

from vtuber.config.loader import AppConfig, load_config
from vtuber.modules.asr.factory import ASRFactory
from vtuber.modules.avatar.factory import AvatarFactory
from vtuber.modules.avatar.live2d_model import Live2dModel
from vtuber.modules.avatar.playwright_manager import PlaywrightManager
from vtuber.modules.llm.factory import LLMFactory
from vtuber.modules.profile.form import ProfileFormStore
from vtuber.modules.tts.factory import TTSFactory
from vtuber.modules.vad.factory import VADFactory
from vtuber.modules.vad.silero import SileroVADBackend

logger = logging.getLogger(__name__)


class ServiceContext:
    """全局模块；线程池按用途隔离，避免 VAD/ASR/磁盘 IO 互相抢默认池。"""

    def __init__(self, config: AppConfig | None = None):
        self.config = config or load_config()
        self.llm = LLMFactory.create(self.config.llm)
        self.asr = ASRFactory.create(self.config.asr)
        self.tts = TTSFactory.create(self.config.tts)
        self.avatar = AvatarFactory.create(self.config.avatar)
        self.playwright = PlaywrightManager(self.config.avatar)
        self.live2d_model: Live2dModel | None = None
        if (
            self.config.avatar.enabled
            and self.config.avatar.live2d_expressions_enabled
        ):
            try:
                self.live2d_model = Live2dModel(
                    self.config.avatar.model_name,
                    self.config.avatar.model_dict_path,
                )
            except Exception:
                logger.exception("Live2D model_dict 加载失败，表情/动作标签已禁用")
        self.profile = ProfileFormStore(self.config.profile)
        self._vad_backend: SileroVADBackend | None = VADFactory.create_backend(
            self.config.vad
        )
        vad_workers = max(1, self.config.system.vad_executor_workers)
        io_workers = max(1, self.config.system.io_executor_workers)
        self._vad_executor = ThreadPoolExecutor(
            max_workers=vad_workers, thread_name_prefix="vad"
        )
        self._io_executor = ThreadPoolExecutor(
            max_workers=io_workers, thread_name_prefix="io"
        )
        logger.info(
            "ServiceContext 已加载 llm/asr/tts/profile/avatar vad=%s asr_pool=%d vad_workers=%d avatar=%s",
            "shared" if self._vad_backend else "off",
            self.config.asr.pool_size,
            vad_workers,
            "playwright" if self.playwright.enabled else "off",
        )

    def new_vad_engine(self):
        """每 WebSocket 连接独立 VAD 状态机，共享 Silero 权重。"""
        if self._vad_backend is None:
            return None
        return VADFactory.create_session(self.config.vad, self._vad_backend)

    async def run_vad(self, fn, *args):
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._vad_executor, fn, *args)

    async def run_io(self, fn, *args):
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._io_executor, fn, *args)

    async def shutdown_async(self) -> None:
        if self.playwright.enabled:
            await self.playwright.shutdown()

    def shutdown(self) -> None:
        self._vad_executor.shutdown(wait=False, cancel_futures=True)
        self._io_executor.shutdown(wait=False, cancel_futures=True)
