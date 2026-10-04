"""Local novel conversion: ordered chapters, bounded archives, portable TXT/EPUB."""
import io
import posixpath
import re
import zipfile
from html import escape
from html.parser import HTMLParser
from pathlib import PurePosixPath
from urllib.parse import unquote
from xml.etree import ElementTree as ET

CHAPTER = re.compile(r"^\s*(?:#{1,6}\s*)?((?:第\s*[\d零〇一二三四五六七八九十百千万两]+\s*[章节回卷部]|chapter\s+\d+)[^\n]{0,100})\s*$", re.I)
CHAPTER_FILE = re.compile(r"(?:^|[-_ ])(?:ch(?:apter)?)[-_ ]?(\d+)", re.I)


def decode(data):
    encodings = ("utf-16",) if data.startswith((b'\xff\xfe', b'\xfe\xff')) else ("utf-8-sig", "gb18030")
    for encoding in encodings:
        try:
            return data.decode(encoding).replace("\r\n", "\n").replace("\r", "\n")
        except UnicodeError:
            pass
    raise ValueError("文字编码无法识别，请使用 UTF-8、UTF-16 或 GB18030")


def split_chapters(text, title="正文"):
    sections, current, lines = [], title, []
    def append():
        body = "\n".join(lines).strip()
        if body:
            sections.append({"title": current, "text": body})
    for line in text.splitlines():
        match = CHAPTER.match(line)
        if match:
            append()
            current, lines = match[1].strip(), []
        else:
            lines.append(line)
    append()
    return sections


class HTMLText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.hidden = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "head"}:
            self.hidden += 1
        if tag in {"p", "div", "br", "h1", "h2", "h3", "li"} and not self.hidden:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in {"script", "style", "head"}:
            self.hidden = max(0, self.hidden - 1)
        if tag in {"p", "div", "h1", "h2", "h3", "li"} and not self.hidden:
            self.parts.append("\n")

    def handle_data(self, text):
        if not self.hidden:
            self.parts.append(text)


def html_text(text):
    parser = HTMLText()
    parser.feed(text)
    return re.sub(r"\n[ \t]*\n(?:[ \t]*\n)+", "\n\n", "".join(parser.parts)).strip()


def safe_name(name):
    path = PurePosixPath(name.replace("\\", "/"))
    if path.is_absolute() or ".." in path.parts or ":" in name or "\x00" in name:
        raise ValueError("文件路径包含不允许的目录信息")
    return str(path)


def archive(data, max_bytes):
    try:
        book = zipfile.ZipFile(io.BytesIO(data))
        entries = book.infolist()
        if len(entries) > 10000 or sum(e.file_size for e in entries) > max_bytes:
            book.close()
            raise ValueError("压缩包展开后的内容超过上限")
        names = set()
        for entry in entries:
            name = safe_name(entry.filename)
            if name in names or entry.flag_bits & 1 or (entry.external_attr >> 16) & 0o170000 == 0o120000:
                book.close()
                raise ValueError("压缩包包含重复路径、加密文件或符号链接")
            names.add(name)
        return book
    except zipfile.BadZipFile:
        raise ValueError("ZIP / EPUB 文件损坏") from None


def xml(data):
    if b"<!ENTITY" in data.upper():
        raise ValueError("EPUB 不支持自定义 XML 实体")
    return ET.fromstring(data)


def read_epub(data, max_bytes):
    with archive(data, max_bytes) as book:
        try:
            container = xml(book.read("META-INF/container.xml"))
            rootfile = next(n.attrib["full-path"] for n in container.iter() if n.tag.endswith("}rootfile"))
            package = xml(book.read(safe_name(rootfile)))
            title = next((n.text for n in package.iter() if n.tag.endswith("}title") and n.text), "导入小说")
            manifest = {n.attrib["id"]: n.attrib for n in package.iter() if n.tag.endswith("}item")}
            sections = []
            for node in package.iter():
                if not node.tag.endswith("}itemref") or node.attrib.get("linear") == "no":
                    continue
                item = manifest[node.attrib["idref"]]
                if "nav" in item.get("properties", "").split():
                    continue
                if item.get("media-type") not in {"application/xhtml+xml", "text/html"}:
                    continue
                href = unquote(item["href"].split("#")[0])
                target = safe_name(posixpath.normpath(posixpath.join(posixpath.dirname(rootfile), href)))
                text = html_text(decode(book.read(target)))
                if text:
                    sections.extend(split_chapters(text, text.splitlines()[0][:100] or "正文"))
            if not sections:
                raise ValueError("EPUB 没有可阅读正文，图片扫描版或受保护内容暂不支持")
            return title, sections
        except (KeyError, StopIteration, ET.ParseError):
            raise ValueError("EPUB 缺少有效目录或章节文件") from None


def natural_key(name):
    return tuple((0, int(p)) if p.isdigit() else (1, p.lower()) for p in re.split(r"(\d+)", name))


def convert(files, max_bytes, max_chars):
    """files are (relative display name, bytes); never extract archives to disk."""
    if not files or sum(len(data) for _, data in files) > max_bytes:
        raise ValueError("未选择文件或文件总量超过上传限制")
    input_title = PurePosixPath(files[0][0].replace("\\", "/")).stem if len(files) == 1 else PurePosixPath(files[0][0].replace("\\", "/")).parts[0]
    if len(files) == 1 and files[0][0].lower().endswith(".epub"):
        title, sections = read_epub(files[0][1], max_bytes)
        ignored = []
    else:
        if len(files) == 1 and files[0][0].lower().endswith(".zip"):
            with archive(files[0][1], max_bytes) as book:
                files = [(e.filename, book.read(e)) for e in book.infolist() if not e.is_dir()]
        if len(files) > 5000:
            raise ValueError("章节文件数量超过5000个")
        files = [(safe_name(name), data) for name, data in files]
        if len({name.casefold() for name, _ in files}) != len(files):
            raise ValueError("存在同名章节文件，请先确认目录结构")
        readable = [(name, data) for name, data in files if PurePosixPath(name).suffix.lower() in {".txt", ".md", ".html", ".htm"}]
        chapter_files = [(name, data) for name, data in readable if CHAPTER_FILE.search(PurePosixPath(name).stem)]
        # Chapter folders often include README and author notes: keep the exclusion visible.
        selected = chapter_files or [(name, data) for name, data in readable if PurePosixPath(name).stem.lower() not in {"readme", "license"} and not any(p.lower() in {"references", "notes", ".git", "__macosx"} for p in PurePosixPath(name).parts)]
        chosen = {name for name, _ in selected}
        ignored = [name for name, _ in files if name not in chosen]
        selected.sort(key=lambda item: natural_key(item[0]))
        sections = []
        title = input_title
        for name, data in selected:
            text = decode(data)
            if PurePosixPath(name).suffix.lower() in {".html", ".htm"}:
                text = html_text(text)
            sections.extend(split_chapters(text, PurePosixPath(name).stem))
    if not sections:
        raise ValueError("未发现可阅读的小说正文")
    if sum(len(s["text"]) + len(s["title"]) for s in sections) > max_chars:
        raise ValueError("小说文字量超过当前解析上限，未截断正文")
    for index, section in enumerate(sections):
        if not CHAPTER.match(section["title"]):
            section["title"] = f"第{index+1}章 {section['title']}"
    return {"title": title, "sections": sections, "ignored_files": ignored}


def as_txt(sections):
    return "\n\n".join(f"{s['title']}\n\n{s['text']}" for s in sections) + "\n"


def as_epub(title, sections):
    from datetime import datetime, timezone
    modified = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as book:
        book.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        book.writestr("META-INF/container.xml", '<?xml version="1.0" encoding="utf-8"?><container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles></container>')
        items, spine, links = [], [], []
        for index, section in enumerate(sections):
            name = f"chapter-{index+1:04d}.xhtml"
            paragraphs = "".join(f"<p>{escape(line)}</p>" for line in section["text"].splitlines() if line.strip())
            book.writestr("OEBPS/" + name, f'<?xml version="1.0" encoding="utf-8"?><html xmlns="http://www.w3.org/1999/xhtml" lang="zh"><head><title>{escape(section["title"])}</title></head><body><h1>{escape(section["title"])}</h1>{paragraphs}</body></html>')
            items.append(f'<item id="c{index}" href="{name}" media-type="application/xhtml+xml"/>')
            spine.append(f'<itemref idref="c{index}"/>')
            links.append(f'<li><a href="{name}">{escape(section["title"])}</a></li>')
        book.writestr("OEBPS/nav.xhtml", f'<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops"><head><title>目录</title></head><body><nav epub:type="toc"><h1>目录</h1><ol>{"".join(links)}</ol></nav></body></html>')
        import hashlib
        identity = hashlib.sha256(as_txt(sections).encode()).hexdigest()
        book.writestr("OEBPS/content.opf", f'<?xml version="1.0" encoding="utf-8"?><package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="book-id" xml:lang="zh"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:identifier id="book-id">urn:sha256:{identity}</dc:identifier><dc:title>{escape(title)}</dc:title><dc:language>zh</dc:language><meta property="dcterms:modified">{modified}</meta></metadata><manifest><item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>{"".join(items)}</manifest><spine>{"".join(spine)}</spine></package>')
    return buffer.getvalue()
