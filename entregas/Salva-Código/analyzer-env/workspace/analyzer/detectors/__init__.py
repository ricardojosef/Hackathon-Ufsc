"""Adapters de detecção, um por ferramenta ou linguagem."""

from .base import Detector, iter_source_files, relative

__all__ = ["Detector", "iter_source_files", "relative"]
