"""Workers 构建时复用本地知识库切块和词频统计。"""
import json
from pathlib import Path

from service.domain.knowledge import Knowledge

index = Knowledge("knowledge")
data = {"chunks": index.chunks, "df": index.df, "avg": index.avg}
Path("workers/domain/index.generated.json").write_text(json.dumps(data, ensure_ascii=False))
