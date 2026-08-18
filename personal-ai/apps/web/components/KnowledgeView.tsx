"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import {
  deleteDocument,
  documentContentUrl,
  fetchDocument,
  fetchDocuments,
  searchPreview,
  uploadFile,
  type DocumentDetail,
  type DocumentStatus,
  type KnowledgeDocument,
  type SearchResult,
} from "@/lib/api";

const statusLabel: Record<DocumentStatus, string> = {
  pending: "等待索引",
  indexing: "索引中",
  indexed: "已索引",
  needs_ocr: "需要 OCR",
  failed: "失败",
};

const statusClass: Record<DocumentStatus, string> = {
  pending: "bg-gray-100 text-gray-700",
  indexing: "bg-blue-100 text-blue-700",
  indexed: "bg-emerald-100 text-emerald-700",
  needs_ocr: "bg-amber-100 text-amber-800",
  failed: "bg-red-100 text-red-700",
};

function formatBytes(value: number) {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / 1024 / 1024).toFixed(1)} MB`;
}

export default function KnowledgeView() {
  const [documents, setDocuments] = useState<KnowledgeDocument[]>([]);
  const [selected, setSelected] = useState<DocumentDetail | null>(null);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResult[]>([]);
  const fileRef = useRef<HTMLInputElement>(null);

  const refresh = useCallback(async () => {
    setDocuments(await fetchDocuments());
  }, []);

  useEffect(() => {
    let cancelled = false;
    fetchDocuments()
      .then((rows) => {
        if (!cancelled) setDocuments(rows);
      })
      .catch((reason) => {
        if (!cancelled) setError(String(reason));
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const handleUpload = async (file?: File) => {
    if (!file) return;
    setUploading(true);
    setError("");
    try {
      const document = await uploadFile(file);
      await refresh();
      setSelected(await fetchDocument(document.id));
    } catch (reason) {
      setError(String(reason));
    } finally {
      setUploading(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  };

  const handleSelect = async (id: string) => {
    setError("");
    try {
      setSelected(await fetchDocument(id));
    } catch (reason) {
      setError(String(reason));
    }
  };

  const handleDelete = async (document: KnowledgeDocument) => {
    if (!window.confirm(`删除“${document.original_filename}”及其索引？`)) return;
    try {
      await deleteDocument(document.id);
      if (selected?.id === document.id) setSelected(null);
      await refresh();
    } catch (reason) {
      setError(String(reason));
    }
  };

  const handleSearch = async (event: React.FormEvent) => {
    event.preventDefault();
    const text = query.trim();
    if (!text) return;
    setError("");
    try {
      setResults(await searchPreview(text));
    } catch (reason) {
      setError(String(reason));
    }
  };

  return (
    <main className="min-h-0 min-w-0 flex-1 overflow-y-auto bg-white">
      <header className="border-b border-gray-200 px-4 py-4 sm:px-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="text-lg font-semibold text-gray-900">知识库</h1>
            <p className="mt-0.5 text-sm text-gray-500">{documents.length} 份资料 · {documents.reduce((sum, item) => sum + item.chunk_count, 0)} 个片段</p>
          </div>
          <label className={`cursor-pointer rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 ${uploading ? "pointer-events-none opacity-60" : ""}`}>
            {uploading ? "正在索引…" : "上传文件"}
            <input
              ref={fileRef}
              type="file"
              accept=".pdf,.docx,.txt,.md"
              className="sr-only"
              disabled={uploading}
              onChange={(event) => void handleUpload(event.target.files?.[0])}
            />
          </label>
        </div>
        {error && <p className="mt-3 text-sm text-red-600" role="alert">{error}</p>}
      </header>

      <div className="grid min-h-0 lg:grid-cols-[minmax(280px,380px)_1fr]">
        <section className="border-b border-gray-200 p-4 lg:border-r lg:border-b-0 sm:p-6" aria-label="文档列表">
          <div className="space-y-2">
            {documents.map((document) => (
              <div key={document.id} className={`rounded-md border p-3 ${selected?.id === document.id ? "border-blue-400 bg-blue-50" : "border-gray-200"}`}>
                <button type="button" onClick={() => void handleSelect(document.id)} className="w-full text-left">
                  <div className="flex min-w-0 items-start gap-2">
                    <span className="min-w-0 flex-1 truncate text-sm font-medium text-gray-900">{document.original_filename}</span>
                    <span className={`shrink-0 rounded px-1.5 py-0.5 text-xs ${statusClass[document.status]}`}>{statusLabel[document.status]}</span>
                  </div>
                  <p className="mt-1 text-xs text-gray-500">{formatBytes(document.size_bytes)} · {document.chunk_count} 个片段</p>
                  {document.error && <p className="mt-1 line-clamp-2 text-xs text-red-600">{document.error}</p>}
                </button>
                <div className="mt-2 flex gap-3 border-t border-gray-100 pt-2 text-xs">
                  <a href={documentContentUrl(document.id)} target="_blank" rel="noreferrer" className="text-blue-700 hover:underline">打开原文</a>
                  <button type="button" onClick={() => void handleDelete(document)} className="text-red-600 hover:underline">删除</button>
                </div>
              </div>
            ))}
            {documents.length === 0 && !uploading && <p className="py-12 text-center text-sm text-gray-400">尚未上传资料</p>}
          </div>
        </section>

        <section className="min-w-0 p-4 sm:p-6" aria-label="文档详情">
          <form onSubmit={handleSearch} className="mb-6 flex gap-2">
            <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="检索知识库" className="min-w-0 flex-1 rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
            <button type="submit" disabled={!query.trim()} className="rounded-md border border-gray-300 px-4 text-sm font-medium hover:bg-gray-50 disabled:opacity-40">检索</button>
          </form>

          {results.length > 0 ? (
            <div className="mb-8">
              <div className="mb-3 flex items-center justify-between">
                <h2 className="text-sm font-semibold text-gray-900">检索结果</h2>
                <button type="button" onClick={() => setResults([])} className="text-xs text-gray-500 hover:text-gray-900">关闭</button>
              </div>
              <div className="space-y-3">
                {results.map((item) => (
                  <a key={item.chunk_id} href={documentContentUrl(item.document_id, item.page_start)} target="_blank" rel="noreferrer" className="block rounded-md border border-gray-200 p-3 hover:border-blue-300">
                    <div className="flex gap-2 text-sm"><span className="font-medium text-blue-700">#{item.retrieval_rank}</span><span className="truncate font-medium">{item.filename}</span></div>
                    <p className="mt-1 text-xs text-gray-500">{item.section || "正文"}</p>
                    <p className="mt-2 line-clamp-3 text-sm leading-6 text-gray-700">{item.content}</p>
                  </a>
                ))}
              </div>
            </div>
          ) : selected ? (
            <div>
              <div className="mb-5 flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0">
                  <h2 className="truncate text-base font-semibold">{selected.original_filename}</h2>
                  <p className="mt-1 text-xs text-gray-500">{selected.embedding_model} · {selected.embedding_dim} 维</p>
                </div>
                <a href={documentContentUrl(selected.id)} target="_blank" rel="noreferrer" className="rounded-md border border-gray-300 px-3 py-1.5 text-sm hover:bg-gray-50">打开原文</a>
              </div>
              <div className="space-y-3">
                {selected.chunks.map((chunk) => (
                  <article key={chunk.id} className="rounded-md border border-gray-200 p-4">
                    <div className="flex flex-wrap items-center gap-2 text-xs text-gray-500">
                      <span>片段 {chunk.chunk_index + 1}</span><span>·</span><span>{chunk.section || "正文"}</span>
                      {chunk.page_start && <span>· 第 {chunk.page_start} 页</span>}
                    </div>
                    <p className="mt-2 whitespace-pre-wrap text-sm leading-6 text-gray-700">{chunk.content}</p>
                  </article>
                ))}
                {selected.chunks.length === 0 && <p className="py-10 text-center text-sm text-gray-400">该文档没有可预览片段</p>}
              </div>
            </div>
          ) : (
            <div className="py-20 text-center text-sm text-gray-400">选择文档查看索引片段</div>
          )}
        </section>
      </div>
    </main>
  );
}
