"""Disk-indexed deterministic discovery; image buffers never contain the dataset."""
from __future__ import annotations

import hashlib
import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from .config import inside
from .contracts import DatasetConfig, Split
from .errors import ConfigurationError

IMAGE_EXTENSIONS = frozenset({'.jpg','.jpeg','.png','.bmp','.tif','.tiff','.webp'})


@dataclass(frozen=True)
class SamplePlan:
    """Paired paths from source inventory, with ambiguity explicitly retained."""
    key: str
    image_path: Path
    annotation_path: Path | None
    split: Split | None
    duplicate_id: bool
    ambiguous_annotation: bool


def walk_files(root: Path, max_depth: int, depth: int = 0) -> Iterator[Path]:
    """Stream directory entries without accumulating or following directory links."""
    if depth>max_depth:raise ConfigurationError('Dataset directory depth exceeds configured limit')
    if not root.exists():return
    with os.scandir(root) as entries:
        for entry in entries:
            path=Path(entry.path)
            if entry.is_symlink() or path.is_junction():
                raise ConfigurationError('Linked dataset entries must be copied into the explicit local root')
            if entry.is_dir(follow_symlinks=False):yield from walk_files(path,max_depth,depth+1)
            elif entry.is_file(follow_symlinks=False):yield path


def generated_split(identity: str, config: DatasetConfig) -> Split:
    """Seeded content-hash assignment keeps duplicates in the same new split."""
    value=int(hashlib.sha256(f'{config.seed}:{identity}'.encode()).hexdigest()[:16],16)/2**64
    if value<config.split_ratios[0]:return 'train'
    if value<sum(config.split_ratios[:2]):return 'val'
    return 'test'


class Inventory:
    """SQLite paths/hashes replace unbounded Python sample/hash collections."""

    def __init__(self, path: Path, config: DatasetConfig, metadata: dict[str, Any]) -> None:
        self.config=config;self.connection=sqlite3.connect(path)
        self.connection.row_factory=sqlite3.Row
        self.connection.execute('PRAGMA cache_size=-2048')
        self.connection.execute('PRAGMA temp_store=FILE')
        self.connection.executescript('''
            CREATE TABLE files(kind TEXT,split TEXT,stem TEXT,path TEXT PRIMARY KEY);
            CREATE INDEX files_pair ON files(split,stem,kind);
            CREATE TABLE samples(path TEXT PRIMARY KEY,sample_id TEXT,split TEXT,source_valid INT,seg_valid INT,
                kind TEXT,empty INT,width INT,height INT,sha TEXT,pixel_sha TEXT,result TEXT);
            CREATE INDEX samples_hash ON samples(pixel_sha,split);
            CREATE TABLE class_counts(id INT PRIMARY KEY,samples INT DEFAULT 0,instances INT DEFAULT 0,pixels INT DEFAULT 0);
            CREATE TABLE issues(code TEXT PRIMARY KEY,n INT DEFAULT 0);
        ''')
        try:self._populate(metadata)
        except BaseException:
            self.connection.close()
            raise

    def _populate(self, metadata: dict[str, Any]) -> None:
        """Populate the index, closing it if any configuration/discovery fails."""
        config=self.config
        declared={s:metadata[s] for s in ('train','val','test') if metadata.get(s) is not None}
        self.preserve_splits=bool(declared)
        count=0
        for split in declared or {'':config.image_dir}:
            image_value=declared[split] if declared else config.image_dir
            if not isinstance(image_value,str):raise ConfigurationError('Split image paths must be local directory strings')
            images=inside(config.dataset_root/image_value,config.dataset_root)
            if not images.is_dir():raise ConfigurationError('Declared image directory is missing: '+image_value)
            annotations=inside(config.dataset_root/config.annotation_dir/split,config.dataset_root)
            for kind,directory in [('image',images),('annotation',annotations)]:
                for path in walk_files(directory,config.max_depth):
                    if kind=='image' and path.suffix.lower() not in IMAGE_EXTENSIONS:continue
                    if kind=='annotation' and path.suffix.lower()!=config.annotation_extension:continue
                    count+=1
                    if count>config.max_records:raise ConfigurationError('Discovery exceeded max_records')
                    stem=path.relative_to(directory).with_suffix('').as_posix()
                    self.connection.execute('INSERT INTO files VALUES(?,?,?,?)',
                        (kind,split,stem,path.relative_to(config.dataset_root).as_posix()))
        self.connection.commit()
        if not self.connection.execute("SELECT 1 FROM files WHERE kind='image' LIMIT 1").fetchone():
            raise ConfigurationError('Dataset contains no supported images')

    def plans(self) -> Iterator[SamplePlan]:
        """Yield paired samples in stable lexical order using the disk index."""
        rows=self.connection.execute('''SELECT f.*,
            (SELECT COUNT(*) FROM files x WHERE x.split=f.split AND x.stem=f.stem AND x.kind='image') ni,
            (SELECT COUNT(*) FROM files x WHERE x.split=f.split AND x.stem=f.stem AND x.kind='annotation') na,
            (SELECT MIN(path) FROM files x WHERE x.split=f.split AND x.stem=f.stem AND x.kind='annotation') annotation
            FROM files f WHERE kind='image' ORDER BY split,stem,path''')
        for row in rows:
            yield SamplePlan(key=row['stem'],image_path=self.config.dataset_root/row['path'],
                annotation_path=self.config.dataset_root/row['annotation'] if row['na']==1 else None,
                split=row['split'] or None,duplicate_id=row['ni']>1,ambiguous_annotation=row['na']>1)

    def orphans(self) -> Iterator[str]:
        """Report annotation-only entries instead of silently discarding them."""
        rows=self.connection.execute('''SELECT path FROM files f WHERE kind='annotation' AND NOT EXISTS
            (SELECT 1 FROM files i WHERE i.kind='image' AND i.split=f.split AND i.stem=f.stem) ORDER BY path''')
        for row in rows:yield str(row['path'])

    def close(self) -> None:
        """Close the disk-backed index deterministically."""
        self.connection.close()
