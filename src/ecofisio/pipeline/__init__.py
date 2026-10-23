"""Pipeline de dados: ingestão imutável, validação, limpeza registrada e camadas."""

from ecofisio.pipeline.cleaning import modified_z, remove_outliers_mad
from ecofisio.pipeline.layers import DataLake, RawFileConflictError, sha256_file
from ecofisio.pipeline.log import LogEntry, ProcessingLog
from ecofisio.pipeline.schemas import LI6800_COLUMNS, FluorescenceSchema, GasExchangeSchema
from ecofisio.pipeline.validate import SchemaStructureError, validate

__all__ = [
    "LI6800_COLUMNS",
    "DataLake",
    "FluorescenceSchema",
    "GasExchangeSchema",
    "LogEntry",
    "ProcessingLog",
    "RawFileConflictError",
    "SchemaStructureError",
    "modified_z",
    "remove_outliers_mad",
    "sha256_file",
    "validate",
]
