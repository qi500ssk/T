"""只检查已选模型目录与常见缓存，不下载模型或扫描整个磁盘。"""
import importlib.util
import json
from pathlib import Path

from infrastructure.paths import data_path


def _json(path):
    if path.stat().st_size > 1_000_000:
        raise ValueError("模型配置文件过大")
    return json.loads(path.read_text(encoding="utf-8"))


def inspect_local_model(raw):
    path = Path(raw).expanduser()
    if not raw or not path.is_absolute() or str(path).startswith(("\\\\", "//")):
        raise ValueError("请输入这台电脑上的绝对模型文件夹路径")
    path = path.resolve(strict=True)
    if not (path / "config.json").is_file():
        # 接受 ModelScope 模型根目录，定位真正的快照，不要求用户了解缓存结构。
        snapshots = path / "snapshots" if (path / "snapshots").is_dir() else path
        candidates = [p for p in list(snapshots.iterdir())[:100] if p.is_dir() and (p / "config.json").is_file()]
        if len(candidates) != 1:
            raise ValueError("请选择包含 config.json 的模型目录；多个快照时请指定其中一个")
        path = candidates[0].resolve()
    config = _json(path / "config.json")
    if not (path / "model.safetensors").is_file() or not (path / "modules.json").is_file():
        raise ValueError("已有模型需包含 model.safetensors 和 modules.json；ONNX 缓存请从下载模型列表选择复用")
    if not (path / "tokenizer.json").is_file():
        raise ValueError("缺少 tokenizer.json，请选择完整的模型目录")
    modules = _json(path / "modules.json")
    allowed = {"sentence_transformers.models." + name for name in ("Transformer", "Pooling", "Normalize")}
    if not isinstance(modules, list) or not modules or len(modules) > 16:
        raise ValueError("模型模块配置无效")
    for module in modules:
        if not isinstance(module, dict) or module.get("type") not in allowed:
            raise ValueError("暂不支持需要自定义 Python 模块的模型")
        module_path = (path / module.get("path", "")).resolve()
        if not module_path.is_relative_to(path):
            raise ValueError("模型模块路径不能超出所选目录")
    dimension = config.get("hidden_size") or config.get("dim")
    for module in modules:
        if module["type"].endswith(".Pooling"):
            pooling = _json(path / module.get("path", "") / "config.json")
            modes = ["cls_token", "max_tokens", "mean_tokens", "mean_sqrt_len_tokens", "weightedmean_tokens", "lasttoken"]
            count = sum(bool(pooling.get("pooling_mode_" + mode)) for mode in modes)
            dimension = pooling.get("word_embedding_dimension", dimension) * max(count, 1)
    if not isinstance(dimension, int) or not 1 <= dimension <= 4096:
        raise ValueError("无法识别有效向量维度")
    return {"path": str(path), "dimension": dimension, "name": path.parent.parent.name if path.parent.name == "snapshots" else path.name,
            "runtime_ready": importlib.util.find_spec("sentence_transformers") is not None}


def discover_local_models():
    roots = [Path("data/models"), Path.home() / ".cache/modelscope/models", Path.home() / ".cache/huggingface/hub"]
    result = []
    for root in roots:
        if not root.is_dir():
            continue
        try:
            for path in list(root.iterdir())[:100]:
                if not any(name in path.name.lower() for name in ("bge", "minilm")):
                    continue
                try:
                    result.append(inspect_local_model(str(path.resolve())))
                except (OSError, ValueError, TypeError, KeyError):
                    continue
        except OSError:
            continue
    return result


def cached_model_directory(model):
    """只检查 FastEmbed 缓存中的完整文件；不把半下载的目录当作已就绪。"""
    from fastembed import TextEmbedding
    description = next((item for item in TextEmbedding.list_supported_models() if item["model"] == model), None)
    if description is None:
        return None
    cache = Path(data_path("embedding-models"))
    source = description["sources"].get("hf")
    candidates = [cache / ("models--" + source.replace("/", "--")) / "snapshots"] if source else []
    directories = []
    try:
        for snapshots in candidates:
            if snapshots.is_dir():
                directories.extend(list(snapshots.iterdir())[:100])
        if cache.is_dir():
            directories.extend(p for p in list(cache.iterdir())[:100] if not p.name.startswith(("models--", ".")))
        required = [description["model_file"], "config.json", "tokenizer.json", "tokenizer_config.json", "special_tokens_map.json"]
        for path in directories:
            if all((path / name).is_file() and (path / name).stat().st_size > 0 for name in required):
                # 老版 tar 缓存的文件结构可能相同，避免把别的模型目录误认为当前模型。
                if path.parent.name == "snapshots" or model.split("/")[-1].lower() in path.name.lower():
                    return str(path.resolve())
    except OSError:
        pass
    return None
