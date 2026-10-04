"""Stable fingerprints for story sources and memory validation."""
import hashlib


def digest(text):
    return hashlib.sha256(text.encode()).hexdigest()
