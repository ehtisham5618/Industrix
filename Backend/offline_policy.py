"""Project-process offline policy; never edit account-wide telemetry consent."""
import os

def configure_local_runtime():
    os.environ['YOLO_OFFLINE']='true'
    os.environ['YOLO_AUTOINSTALL']='false'
    try:
        import openvino_telemetry
    except ImportError:
        return  # SDK telemetry is not installed in this environment.
    try:
        from openvino_telemetry.utils.opt_in_checker import OptInChecker,ConsentCheckResult
    except ImportError as exc:
        raise RuntimeError('Installed telemetry SDK requires review of the process offline-policy adapter') from exc
    # The installed SDK has a machine/user consent file, but no process-only
    # opt-out switch. Adapt its consent check before any engine import. Returning
    # DECLINED suppresses all emitter initializations without touching that file.
    def declined(self,*args,**kwargs):return ConsentCheckResult.DECLINED
    OptInChecker.check=declined
