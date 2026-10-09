"""Streaming two-class metrics, zero-division handling and no invented targets."""
from __future__ import annotations
import numpy as np
from .common import CLASSES
from .contracts import EvaluationResult,PerClassMetrics


def metrics(confusion: np.ndarray) -> EvaluationResult:
    """Rows are actual, columns predicted; undefined precision/recall become0."""
    if confusion.shape!=(2,2) or np.any(confusion<0) or not np.issubdtype(confusion.dtype,np.integer):raise ValueError('Expected nonnegative2x2 confusion matrix')
    total=int(confusion.sum())
    if not total:raise ValueError('Cannot evaluate an empty split')
    rows=[]
    for i in range(2):
        tp=int(confusion[i,i]);actual=int(confusion[i].sum());predicted=int(confusion[:,i].sum())
        precision=tp/predicted if predicted else 0.;recall=tp/actual if actual else 0.
        f1=2*precision*recall/(precision+recall) if precision+recall else 0.
        rows.append(PerClassMetrics(class_id=i,class_name=CLASSES[i],support=actual,precision=precision,recall=recall,f1=f1))
    return EvaluationResult(samples=total,accuracy=float(np.trace(confusion)/total),macro_precision=sum(r.precision for r in rows)/2,
        macro_recall=sum(r.recall for r in rows)/2,macro_f1=sum(r.f1 for r in rows)/2,confusion_matrix=confusion.tolist(),per_class=rows)
