import logging
import os
from functools import wraps

from tqdm import tqdm

DEFAULT_TQDM_LOGGING_INTERVAL = 5.0


logger = logging.getLogger(__name__)


class LoggingTQDM(tqdm):

    def __init__(self, *args, **kwargs):  # noqa: D107

        if "mininterval" not in kwargs:
            kwargs["mininterval"] = DEFAULT_TQDM_LOGGING_INTERVAL

        super().__init__(*args, **kwargs)
        self.sp = logger
        self.fp = open(os.devnull, "w")  # noqa: SIM115, PTH123

        if hasattr(self, "_old_update"):
            return

        self._old_update = super().update

    def close(self) -> None:
        """Cleanup and (if leave=False) close the progressbar."""
        if self.disable:
            return

        # Prevent multiple closures
        self.disable = True

        # decrement instance pos and remove from internal set
        pos = abs(self.pos)
        self._decr_instances(self)

        if self.last_print_t < self.start_t + self.delay:
            # haven't ever displayed; nothing to clear
            return

        # GUI mode
        if getattr(self, "sp", None) is None:
            return

        leave = pos == 0 if self.leave is None else self.leave

        with self._lock:
            if leave:
                # stats for overall rate (no weighted average)
                self._ema_dt = lambda: None
                self.display(pos=0)

    def clear(self, nolock: bool = False) -> None:
        """Clear current bar display."""
        return

    def display(self, msg: str | None = None, pos: int | None = None) -> bool:
        """
        Use `self.sp` to display `msg` in the specified `pos`.

        Consider overloading this function when inheriting to use e.g.:
        `self.some_frontend(**self.format_dict)` instead of `self.sp`.

        Parameters
        ----------
        msg  : str, optional. What to display (default: `repr(self)`).
        pos  : int, optional. Position to `moveto`
          (default: `abs(self.pos)`).
        """

        if pos is None:
            pos = abs(self.pos)

        nrows = self.nrows or 20
        if pos >= nrows - 1:
            if pos >= nrows:
                return False
            if msg or msg is None:  # override at `nrows - 1`
                msg = " ... (more hidden) ..."

        msg = self.__str__() if msg is None else msg

        if len(msg) > 0:
            logger.info(msg)

        return True

    def update(self, n: float = 1) -> bool | None:
        updated = self._old_update(n)
        # updated = super().update(n)
        if updated:
            return None

        if self.n < self.total:
            return None

        self.refresh(lock_args=self.lock_args)
        self.disable = True

        return True


__original_tqdm_init__ = tqdm.__init__


# Создаем патч
@wraps(__original_tqdm_init__)
def new_init(self: tqdm, *args, **kwargs) -> None:
    # Если mininterval не указан, устанавливаем его значение в 5.0
    if "mininterval" not in kwargs:
        kwargs["mininterval"] = DEFAULT_TQDM_LOGGING_INTERVAL

    # Вызываем оригинальный метод с измененными параметрами
    __original_tqdm_init__(self, *args, **kwargs)


def patch_tqdm() -> None:
    if hasattr(tqdm, "_old_update"):
        # Already patched
        return

    logger.info("Patching tqdm for logging output")
    tqdm.__init__ = new_init
    tqdm.close = LoggingTQDM.close
    tqdm.clear = LoggingTQDM.clear
    tqdm.display = LoggingTQDM.display
    tqdm._old_update = tqdm.update  # noqa: SLF001
    tqdm.update = LoggingTQDM.update
