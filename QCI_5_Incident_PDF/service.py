"""Bounded local evidence, readable A4 flowables and verified atomic PDF output."""
from contextlib import ExitStack
from datetime import datetime, timezone
from html import escape
import hashlib
import gc
import io
import logging
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import time
from PIL import Image as PILImage
from pydantic import ValidationError
from pypdf import PdfReader
import reportlab
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image, PageBreak
from .adapter import Adapter, identity, local_path
from .contracts import ExportResult, ReportData

LOG=logging.getLogger('qci5')
_FONT_LOCK=threading.Lock()
_OUTPUT_LOCKS=tuple(threading.RLock() for _ in range(64))

def open_image(stream):
    # Follow the repository's QCI-1 decoder safeguard without importing its CV
    # pipeline. Ultralytics globally wraps Pillow and installs HEIF on corruption.
    opener=PILImage.open
    if getattr(opener,'__module__','')=='ultralytics.utils.patches':
        native=getattr(sys.modules.get('ultralytics.utils.patches'),'_image_open',None)
        if native is None or getattr(native,'__module__','')!='PIL.Image':
            raise RuntimeError('Verified native Pillow decoder unavailable')
        opener=native
    return opener(stream)

def filename(incident_id):
    identity(incident_id)
    # Windows filename budget includes suffix; retain complete ID inside the PDF.
    token=incident_id if len(incident_id)<=180 else incident_id[:100]+'-'+hashlib.sha256(incident_id.encode()).hexdigest()[:24]
    return token+'_incident_report.pdf'

def fonts():
    """ReportLab's bundled local Vera fonts; no operating-system font dependency."""
    with _FONT_LOCK:
        if 'QCI5Vera' not in pdfmetrics.getRegisteredFontNames():
            root=Path(reportlab.__file__).parent/'fonts'
            pdfmetrics.registerFont(TTFont('QCI5Vera',str(root/'Vera.ttf')))
            pdfmetrics.registerFont(TTFont('QCI5VeraBold',str(root/'VeraBd.ttf')))
    return 'QCI5Vera','QCI5VeraBold'

def validate_pdf(data, report):
    if len(data)<100 or not data.startswith(b'%PDF-'): raise ValueError('Invalid PDF output')
    with io.BytesIO(data) as stream, PdfReader(stream,strict=True) as pdf:
        if not pdf.pages: raise ValueError('Empty PDF')
        text='\n'.join(page.extract_text() for page in pdf.pages)
        # Class/location may contain glyph substitutions; primary IDs/severity are ASCII.
        if report.incident_id not in text.replace('\n','') or report.severity.upper() not in text:
            raise ValueError('Required incident identity/severity missing from PDF')

class PDFService:
    def __init__(self, adapter):
        self.adapter=adapter; self.config=adapter.config

    def prepare(self,evidence,stack,warnings,incident_id):
        try:
            path=local_path(evidence.path)
            if not any(path.is_relative_to(root) for root in self.adapter.allowed_roots()): raise ValueError('Evidence outside configured roots')
            # Open once; bounded read avoids a stat/read race causing unlimited allocation.
            with path.open('rb') as handle: content=handle.read(self.config.max_image_bytes+1)
            if len(content)>self.config.max_image_bytes: raise ValueError('Evidence byte budget exceeded')
            if evidence.sha256 and hashlib.sha256(content).hexdigest()!=evidence.sha256: raise ValueError('Evidence integrity mismatch')
            with io.BytesIO(content) as source, open_image(source) as image:
                w,h=image.size
                if min(w,h)<1 or w*h>self.config.max_image_pixels: raise ValueError('Evidence pixel budget exceeded')
                image.load()
                # A resized copy, never modify original; retain at most 1200x1200 RGB pixels.
                image.thumbnail((1200,1200))
                with image.convert('RGB') as reduced:
                    buffer=stack.enter_context(io.BytesIO()); reduced.save(buffer,format='JPEG',quality=85)
                    buffer.seek(0); rw,rh=reduced.size
                del content
            flow=Image(buffer)
            scale=min((A4[0]-36*mm)/rw,100*mm/rh,1)
            flow.drawWidth=rw*scale;flow.drawHeight=rh*scale;flow.hAlign='LEFT'
            return flow
        except (OSError,ValueError,RuntimeError,PILImage.DecompressionBombError) as exc:
            kind='EVIDENCE_MISSING' if isinstance(exc,FileNotFoundError) else 'EVIDENCE_INVALID'
            warning=kind+': '+evidence.role
            if warning not in warnings: warnings.append(warning)
            LOG.warning('%s incident_id=%s error_type=%s',kind,incident_id,type(exc).__name__)
            return None

    def render(self,report):
        try:
            content,warnings,evidence_ms,render_ms=self._render(report)
        finally:
            # PDF object graphs include cycles. Release them after the inner
            # renderer's locals/buffers have left scope, on the real service path
            # (including failures), rather than waiting for allocator thresholds.
            cleanup_started=time.perf_counter()
            gc.collect()
            cleanup_ms=(time.perf_counter()-cleanup_started)*1000
        return content,warnings,evidence_ms,render_ms+cleanup_ms

    def _render(self,report):
        report=ReportData.model_validate(report.model_dump())
        regular,bold=fonts();warnings=list(report.warnings)
        glyphs=pdfmetrics.getFont(regular).face.charWidths
        def plain(value):
            text=str(value if value is not None else 'Not provided')
            cleaned=[]
            for char in text:
                if char in '\n\t' or ord(char) in glyphs: cleaned.append(char)
                else:
                    cleaned.append('[U+%04X]'%ord(char))
                    warning='FONT_UNSUPPORTED: U+%04X rendered as code point'%ord(char)
                    if warning not in warnings and len(warnings)<32: warnings.append(warning)
            return ''.join(cleaned)
        styles={
            'body':ParagraphStyle('QCI5Body',fontName=regular,fontSize=10,leading=15,spaceAfter=5,splitLongWords=True),
            'small':ParagraphStyle('QCI5Small',fontName=regular,fontSize=9,leading=13,spaceAfter=4,splitLongWords=True),
            'title':ParagraphStyle('QCI5Title',fontName=bold,fontSize=20,leading=26,textColor=colors.HexColor('#17344d'),spaceAfter=9),
            'section':ParagraphStyle('QCI5Section',fontName=bold,fontSize=12,leading=17,textColor=colors.HexColor('#17344d'),spaceBefore=12,spaceAfter=7,keepWithNext=True)}
        def p(value,style='body'): return Paragraph(escape(plain(value)).replace('\n','<br/>'),styles[style])
        def section(value): return p(value,'section')
        width=A4[0]-36*mm
        def table(rows):
            t=Table([[p(k,'small'),p(v)] for k,v in rows],colWidths=[46*mm,width-46*mm],hAlign='LEFT',splitInRow=1)
            t.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'),('BACKGROUND',(0,0),(0,-1),colors.HexColor('#eef3f7')),
                ('LINEBELOW',(0,0),(-1,-1),.4,colors.HexColor('#dbe3eb')),('LEFTPADDING',(0,0),(-1,-1),8),('RIGHTPADDING',(0,0),(-1,-1),8),
                ('TOPPADDING',(0,0),(-1,-1),6),('BOTTOMPADDING',(0,0),(-1,-1),6)]))
            return t
        now=datetime.now(timezone.utc).isoformat(timespec='seconds')
        with ExitStack() as stack:
            buffer=stack.enter_context(io.BytesIO())
            story=[p('IndusriX','small'),p(self.config.title,'title'),p('Internal Quality / Safety Incident Record','small'),
                p('Generated locally (UTC): '+now+' | '+self.config.report_version,'small')]
            if report.is_sample: story.append(p('SAMPLE / DEMONSTRATION - research or controlled test data; no operational incident asserted.'))
            story += [section('Incident summary'),table([('Incident / event ID',report.incident_id+'\n'+report.event_id),
                ('Recorded timestamp (UTC)',report.timestamp.isoformat()),('Severity / status',report.severity.upper()+' / '+report.state.upper()),
                ('Source',report.source_id),('Location',report.location),('Source sample identity',report.sample_id)]),
                section('Detection details'),table([('Defect / anomaly class',report.defect_class),
                ('Confidence',f'{report.confidence*100:.1f}%' if report.confidence is not None else 'Unavailable'),
                ('Model / policy',str(report.model_version or 'Unavailable')+'\n'+str(report.policy_version or 'Unavailable'))])]
            if report.bbox: story.append(table([('Bounding box / track',str(report.bbox)+'; xyxy source-frame pixels; track '+str(report.track_id))]))
            # A clear evidence/review page boundary also keeps the metadata legible.
            story += [PageBreak(),section('Local visual evidence')]
            started=time.perf_counter();shown=set()
            for evidence in report.evidence:
                if evidence.role=='Model Attribution Heatmap' and not self.config.include_heatmap: continue
                flow=self.prepare(evidence,stack,warnings,report.incident_id)
                story.append(section(evidence.role));shown.add(evidence.role)
                story.append(flow if flow else p(evidence.role+' unavailable'))
                story.append(p(evidence.context,'small'))
                if evidence.sha256: story.append(p('Source SHA-256: '+evidence.sha256,'small'))
            evidence_ms=(time.perf_counter()-started)*1000
            if 'Evidence image' not in shown:
                story.append(p('Evidence image unavailable'));warnings.append('EVIDENCE_MISSING: Evidence image')
                LOG.warning('EVIDENCE_MISSING incident_id=%r role=Evidence_image',report.incident_id)
            if self.config.include_heatmap and 'Model Attribution Heatmap' not in shown:
                story.append(p('QCI-2 heatmap unavailable for this incident.'));warnings.append('EVIDENCE_MISSING: Model Attribution Heatmap')
                LOG.warning('EVIDENCE_MISSING incident_id=%r role=Model_Attribution_Heatmap',report.incident_id)
            story += [section('Alarm state and delivery'),table([('Recorded severity / state',report.severity.upper()+' / '+report.state.upper()),
                ('Siren delivery status',report.delivery or 'Not recorded'),('Delivery attempts',report.delivery_attempts),
                ('Delivery interpretation','An acknowledgement records receiver delivery only; physical siren actuation is not asserted.')])]
            if report.transitions:
                story.append(section('Retained event transitions'))
                for transition in report.transitions:
                    story.append(p(transition.timestamp+' | '+transition.state))
                    if transition.detail: story.append(p(transition.detail,'small'))
            if self.config.include_telemetry:
                story.append(section('Edge telemetry'))
                t=report.telemetry
                if t:
                    story.append(p(t.context+'; sample UTC: '+t.timestamp.isoformat()))
                    story.append(table([('Edge / cloud / mode',t.edge_status+' / '+t.cloud_status+' / '+t.mode),('Pending sync',t.pending),
                        ('System CPU',f'{t.cpu_percent:.1f}%' if t.cpu_percent is not None else 'Unavailable'),
                        ('Process memory',f'{t.process_rss_mb:.2f} MiB' if t.process_rss_mb is not None else 'Unavailable')]))
                else: story.append(p('Telemetry unavailable. No incident-time telemetry was stored.'))
            story += [section('Operator review and sign-off'),table([('Reviewed By',report.operator_name or '____________________________'),
                ('Signature / date','____________________________ / ____________________')]),
                section('Comments'),p(report.operator_notes or 'Pending operator review'),
                section('Corrective action'),p(report.corrective_action or 'Pending operator review'),Spacer(1,4*mm),
                p('This report is generated from local IndusriX detection and event data for operational review. Automated detection results should be reviewed by an authorized operator where required.','small')]
            if warnings: story += [section('Export warnings'),*[p(w,'small') for w in dict.fromkeys(warnings)]]
            def footer(canvas,doc):
                canvas.saveState();canvas.setFont(regular,8);canvas.setFillColor(colors.HexColor('#526478'))
                canvas.line(18*mm,17*mm,A4[0]-18*mm,17*mm)
                token=report.incident_id if len(report.incident_id)<65 else report.incident_id[:36]+'... / '+hashlib.sha256(report.incident_id.encode()).hexdigest()[:12]
                canvas.drawString(18*mm,12*mm,'Generated locally | '+token)
                canvas.drawRightString(A4[0]-18*mm,8*mm,'Page '+str(doc.page)+' | '+self.config.report_version)
                canvas.restoreState()
            doc=SimpleDocTemplate(buffer,pagesize=A4,leftMargin=18*mm,rightMargin=18*mm,topMargin=18*mm,bottomMargin=25*mm,
                title=self.config.title+' - '+report.incident_id,author='IndusriX',subject='Internal quality/event record',creator='IndusriX '+self.config.report_version)
            started=time.perf_counter();doc.build(story,onFirstPage=footer,onLaterPages=footer)
            content=buffer.getvalue();validate_pdf(content,report)
            render_ms=(time.perf_counter()-started)*1000
        return content,list(dict.fromkeys(warnings)),evidence_ms,render_ms

    def generate(self,incident_id,subdirectory=None):
        # Fixed-size lock stripes: concurrent same-ID writes serialize without an
        # ever-growing lock/cache dictionary. Distinct IDs can still render concurrently.
        key=int(hashlib.sha256(incident_id.encode()).hexdigest()[:8],16)%len(_OUTPUT_LOCKS)
        with _OUTPUT_LOCKS[key]:return self._generate(incident_id,subdirectory)

    def _generate(self,incident_id,subdirectory=None):
        began=time.perf_counter();temporary=None;lookup=0;evidence=0;render=0;write=0
        LOG.info('PDF_EXPORT_STARTED incident_id=%r',incident_id)
        try:
            name=filename(incident_id)
            root=local_path(self.config.output_dir)
            target_dir=root if subdirectory is None else local_path(root/subdirectory)
            if not target_dir.is_relative_to(root): raise ValueError('Output escapes configured report root')
            start=time.perf_counter();report=self.adapter.load(incident_id);lookup=(time.perf_counter()-start)*1000
            content,warnings,evidence,render=self.render(report)
            target_dir.mkdir(parents=True,exist_ok=True);target=target_dir/name
            if not target.resolve().is_relative_to(root): raise ValueError('Output target escapes configured report root')
            start=time.perf_counter()
            with tempfile.NamedTemporaryFile(dir=target_dir,prefix='.qci5-',suffix='.tmp',delete=False) as handle:
                temporary=Path(handle.name);handle.write(content);handle.flush();os.fsync(handle.fileno())
            # Windows readers may briefly hold a non-delete-sharing handle. Retry
            # only that sharing/permission error; retain the previous final on failure.
            for attempt in range(8):
                try:os.replace(temporary,target);break
                except PermissionError:
                    if attempt==7:raise
                    time.sleep(.02)
            temporary=None;write=(time.perf_counter()-start)*1000
            result=ExportResult(status='SUCCESS',incident_id=incident_id,output_path=str(target),size_bytes=len(content),
                latency_ms=(time.perf_counter()-began)*1000,lookup_ms=lookup,evidence_ms=evidence,render_ms=render,write_ms=write,
                sha256=hashlib.sha256(content).hexdigest(),warnings=warnings,report_version=self.config.report_version)
            LOG.info('PDF_EXPORT_COMPLETED incident_id=%s output=%s latency_ms=%.3f size_bytes=%s',incident_id,target,result.latency_ms,result.size_bytes)
            return result
        except Exception as exc:
            error='NOT_FOUND' if isinstance(exc,KeyError) else 'INVALID_INPUT' if isinstance(exc,(ValueError,ValidationError)) else 'STORAGE_UNAVAILABLE' if isinstance(exc,(OSError,sqlite3.Error)) else 'EXPORT_FAILED'
            LOG.error('PDF_EXPORT_FAILED incident_id=%r error_type=%s latency_ms=%.3f',incident_id,type(exc).__name__,(time.perf_counter()-began)*1000)
            return ExportResult(status='FAILED',incident_id=incident_id,latency_ms=(time.perf_counter()-began)*1000,
                lookup_ms=lookup,evidence_ms=evidence,render_ms=render,write_ms=write,error=error,report_version=self.config.report_version)
        finally:
            if temporary:
                try: temporary.unlink(missing_ok=True)
                except OSError: LOG.error('PDF_TEMP_CLEANUP_FAILED incident_id=%s',incident_id)
