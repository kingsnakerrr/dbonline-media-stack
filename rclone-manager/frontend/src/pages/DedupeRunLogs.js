import React, { useCallback, useEffect, useState } from 'react';
import { ChevronLeft, ChevronRight, RefreshCw } from 'lucide-react';
import toast from 'react-hot-toast';
import { getDedupeRun, getDedupeRuns } from '../services/api';

const sizeText = (size) => size < 0 ? '目录' : size >= 1073741824 ? `${(size / 1073741824).toFixed(2)} GB` : size >= 1048576 ? `${(size / 1048576).toFixed(2)} MB` : size >= 1024 ? `${(size / 1024).toFixed(1)} KB` : `${size} B`;

function ContentSnapshot({ title, copies }) {
  return <div className="rounded-lg border bg-gray-50 p-3 min-w-0">
    <h4 className="text-sm font-medium mb-2">{title}</h4>
    {!copies?.length && <p className="text-xs text-gray-500">无可用快照</p>}
    {(copies || []).map((copy, index) => <div key={`${copy.id || copy.label}-${index}`} className="mb-3 last:mb-0">
      <div className="text-xs text-gray-700 font-semibold break-all">{copy.label} · {copy.entries?.length || 0} 项{copy.truncated ? '（仅显示前 500 项）' : ''}</div>
      {copy.error && <p className="text-xs text-red-600 break-all">{copy.error}</p>}
      <div className="mt-1 max-h-56 overflow-auto divide-y text-xs text-gray-600">{(copy.entries || []).map((entry, itemIndex) => <div key={`${entry.path}-${itemIndex}`} className="flex justify-between gap-3 py-1"><span className="break-all">{entry.is_dir ? '📁 ' : '📄 '}{entry.path}</span><span className="shrink-0">{entry.is_dir ? '目录' : sizeText(entry.size)}</span></div>)}</div>
    </div>)}
  </div>;
}

export default function DedupeRunLogs() {
  const taskId = new URLSearchParams(window.location.search).get('task_id') || '';
  const [page, setPage] = useState(1);
  const [runs, setRuns] = useState([]);
  const [total, setTotal] = useState(0);
  const [selected, setSelected] = useState(null);
  const [loading, setLoading] = useState(false);
  const load = useCallback(async () => {
    setLoading(true);
    try { const response = await getDedupeRuns(page, taskId); setRuns(response.data?.list || []); setTotal(response.data?.total || 0); }
    catch (error) { toast.error(error.response?.data?.error || '读取去重日志失败'); }
    finally { setLoading(false); }
  }, [page, taskId]);
  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    if (!selected || !['queued', 'scanning', 'applying'].includes(selected.status)) return undefined;
    const timer = window.setInterval(async () => {
      try {
        const response = await getDedupeRun(selected.id);
        setSelected(response.data);
        if (!['queued', 'scanning', 'applying'].includes(response.data.status)) load();
      } catch (_) { /* The manual refresh button remains available. */ }
    }, 5000);
    return () => window.clearInterval(timer);
  }, [selected, load]);
  const open = async (run) => {
    try { const response = await getDedupeRun(run.id); setSelected(response.data); }
    catch (error) { toast.error(error.response?.data?.error || '读取运行详情失败'); }
  };
  return <div className="space-y-4">
    <div className="flex flex-wrap items-center justify-between gap-3"><div><h2 className="text-lg font-semibold">去重运行日志</h2><p className="text-xs text-gray-500">每次检查或执行单独留档。修复前已完成的任务没有合并前快照，无法补录。</p></div><button onClick={load} className="inline-flex gap-1 items-center px-3 py-2 border rounded-lg text-sm"><RefreshCw size={15} />刷新</button></div>
    {loading && <p className="text-sm text-gray-500">正在读取…</p>}
    {!loading && runs.length === 0 && <p className="text-sm text-gray-500 py-8 text-center">暂无去重运行记录</p>}
    <div className="space-y-2">{runs.map((run) => <button key={run.id} onClick={() => open(run)} className={`w-full text-left rounded-lg border p-3 hover:bg-blue-50 ${selected?.id === run.id ? 'border-blue-500' : ''}`}><div className="flex flex-wrap justify-between gap-2"><span className="font-medium break-all">#{run.id} · {run.task_name}</span><span className="text-sm">{run.status === 'complete' ? '已完成' : run.status === 'failed' ? '失败' : run.status === 'cancelled' ? '已取消' : run.status === 'interrupted' ? '被重启中断' : '运行中'}</span></div><p className="text-xs text-gray-500 mt-1 break-all">{run.action} · {run.started_at ? new Date(run.started_at).toLocaleString() : '-'} · {run.summary || '等待结果'}</p></button>)}</div>
    {total > 20 && <div className="flex items-center justify-end gap-3"><button disabled={page <= 1} onClick={() => setPage(page - 1)}><ChevronLeft size={18} /></button><span className="text-sm">第 {page} 页 · 共 {total} 次</span><button disabled={page * 20 >= total} onClick={() => setPage(page + 1)}><ChevronRight size={18} /></button></div>}
    {selected && <div className="rounded-xl border p-4 space-y-4"><div className="flex justify-between gap-2"><div><h3 className="font-semibold">运行 #{selected.id} · {selected.action}</h3><p className="text-xs text-gray-500 break-all">目标：{selected.target} · 开始：{new Date(selected.started_at).toLocaleString()} · 结束：{selected.finished_at ? new Date(selected.finished_at).toLocaleString() : '进行中'}</p></div><button onClick={() => setSelected(null)} className="text-sm text-blue-700">收起</button></div>
      {(selected.operations || []).map((operation, index) => <div key={`${operation.path}-${index}`} className="rounded-lg border p-4 space-y-3"><div className="font-medium break-all">{operation.path} · {operation.status === 'scanned' ? '仅检查' : operation.status === 'complete' ? '已处理' : operation.status === 'skipped' ? '已跳过' : '失败'}</div><p className="text-xs text-gray-600 break-all">{operation.status === 'scanned' ? '检查方式' : '处理方式'}：{operation.command}</p>{operation.summary && <p className="text-sm text-blue-800 break-all">{operation.summary}</p>}{operation.error && <p className="text-xs text-red-700 break-all">{operation.error}</p>}<div className="grid md:grid-cols-2 gap-3"><ContentSnapshot title={operation.status === 'scanned' ? '检查时 · 每个副本原有内容' : '处理前 · 每个副本原有内容'} copies={operation.before} />{operation.status !== 'scanned' && <ContentSnapshot title="处理后 · 合并保留内容" copies={operation.after} />}</div>{operation.output && <details className="text-xs"><summary className="cursor-pointer text-blue-700">查看 rclone 原始处理输出</summary><pre className="mt-2 p-3 rounded-lg bg-gray-950 text-gray-100 overflow-auto max-h-64 whitespace-pre-wrap break-all">{operation.output}</pre></details>}</div>)}
      <div><h4 className="font-medium text-sm mb-2">时间线</h4><div className="bg-gray-950 text-gray-100 rounded-lg p-3 max-h-64 overflow-auto text-xs font-mono space-y-1">{(selected.logs || []).map((line, index) => <div key={index} className="break-all">{line}</div>)}</div></div>
    </div>}
  </div>;
}
