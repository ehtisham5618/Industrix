"""Build local, lossless repeated-image clips; processing remains production code."""
import json
import subprocess
from pathlib import Path
from ESE_CPU1_Quantization.common import ROOT,digest

TASK=ROOT/'IFE_UI3_Demo_Packaging'
CONFIG=TASK/'configs/demo.json'
ASSET=ROOT/'tests/assets/ife_ui3_fire.png'

def main():
    runtime=TASK/'runtime';runtime.mkdir(parents=True,exist_ok=True)
    manifest=json.loads((TASK/'reports/fixture_provenance.json').read_text(encoding='utf-8'))
    if digest(ASSET)!=manifest['fixture_sha256']:raise RuntimeError('Fixture hash mismatch')
    # Lossless H.264 avoids compression drift. Decoder color-space conversion
    # can round pixels; the rehearsal verifies actual decoded model predictions.
    for name,lead in [('hazard_ready.mp4',0),('hazard_timed.mp4',75)]:
        args=['ffmpeg','-hide_banner','-loglevel','error','-y','-loop','1','-framerate','25','-i',str(ASSET)]
        if lead:args+=['-vf',f'drawbox=x=0:y=0:w=iw:h=ih:color=black:t=fill:enable=lt(t\\,{lead})']
        args+=['-t',str(lead+160),'-c:v','libx264','-threads','1','-preset','ultrafast','-crf','0','-pix_fmt','yuv444p',str(runtime/name)]
        subprocess.run(args,check=True)
    textile=ROOT/'tests/assets/ife_ui3_textile.png'
    subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-y','-loop','1','-framerate','25','-i',str(textile),
        '-vf','scale=640:640:force_original_aspect_ratio=decrease,pad=640:640:(ow-iw)/2:(oh-ih)/2:color=0x727272',
        '-t','250','-c:v','libx264','-threads','1','-preset','ultrafast','-crf','0','-pix_fmt','yuv444p',str(runtime/'textile_demo.mp4')],check=True)
    subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-y','-i',str(ROOT/'Confidence_Calibration/benchmark/media/no_helmet_01_workers_roof.webm'),
        '-vf','scale=640:360','-c:v','libx264','-threads','1','-preset','ultrafast','-crf','18','-pix_fmt','yuv420p','-an',str(runtime/'workers_demo.mp4')],check=True)
    base=json.loads((ROOT/'SED_1_Multi_Camera/configs/3_cameras.json').read_text(encoding='utf-8'))
    base.update(scene_note='DEMO: Camera 01 repeats a letterboxed textile dataset image. Camera 02 repeats a dataset fire image after 75 seconds black standby. Camera 03 uses a resized existing public stand-in video. These are not installed factory bays.',
                demo_version='IFEUI3-local-demo-v1')
    base['cameras']['camera_02']['source']='IFE_UI3_Demo_Packaging/runtime/hazard_timed.mp4'
    base['cameras']['camera_01']['source']='IFE_UI3_Demo_Packaging/runtime/textile_demo.mp4'
    base['cameras']['camera_03']['source']='IFE_UI3_Demo_Packaging/runtime/workers_demo.mp4'
    CONFIG.parent.mkdir(parents=True,exist_ok=True)
    CONFIG.write_text(json.dumps(base,indent=2)+'\n',encoding='utf-8')
    ready=json.loads(json.dumps(base));ready['cameras']['camera_02']['source']='IFE_UI3_Demo_Packaging/runtime/hazard_ready.mp4'
    (TASK/'configs/rehearsal.json').write_text(json.dumps(ready,indent=2)+'\n',encoding='utf-8')
    print('Prepared genuine fire fixture clips and camera configs. No detection outputs are injected.')

if __name__=='__main__':main()
