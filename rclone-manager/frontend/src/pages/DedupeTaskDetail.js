import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { ArrowLeft, ExternalLink, Play, Square, Trash2 } from 'lucide-react';
import toast from 'react-hot-toast';
import { applyManagedDedupeTask, deleteManagedDedupeTask, getDedupeTask, startManagedDedupeTask, stopManagedDedupeTask, updateDedupeTask } from '../services/api';

const running = (status) => ['queued', 'scanning', 'applying'].includes(status);
const actionable = (finding) => finding.kind === 'merge' || finding.kind === 'empty';
export default function DedupeTaskDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [task, setTask] = useState(null);
  const [selected, setSelected] = useState([]);
  const [interval, setIntervalValue] = useState(null);
  const [busy, setBusy] = useState(false);
  const [jumpPath, setJumpPath] = useState('');
  const refresh = useCallback(async () => {
    try {
      const response = await getDedupeTask(id);
      setTask(response.data);
      setIntervalValue((current) => current ?? (response.data.interval_minutes || 60));
    } catch (error) { toast.error(error.response?.data?.error || '读取任务失败'); }
  }, [id]);
  useEffect(() => { setIntervalValue(null); refresh(); const timer = window.setInterval(refresh, 2000); return () => window.clearInterval(timer); }, [refresh]);

  const choices = useMemo(() => (task?.findings || []).filter(actionable), [task]);
  const allSelected = choices.length > 0 && choices.every((finding) => selected.includes(finding.id));
  const openDirectory = (rawPath, isFile = false) => {
    const value = rawPath.trim().replace(/\\/g, '/');
    if (!value || !value.startsWith('/') || value.split('/').includes('..') || value.includes(':')) {
      toast.error('请输入当前存储中的绝对目录路径');
      return;
    }
    const directory = isFile ? value.slice(0, value.lastIndexOf('/')) || '/' : value;
    const query = new URLSearchParams({ type: task.source_type, path: directory, from: `/dedupe-tasks/${id}` });
    if (task.source_type === 'remote') query.set('remote', task.remote);
    navigate(`/files?${query.toString()}`);
  };
  const act = async (action) => {
    if (action === 'delete' && !window.confirm('删除这个任务并停止正在运行的去重吗？')) return;
    setBusy(true);
    try {
      if (action === 'start') await startManagedDedupeTask(id);
      if (action === 'stop') await stopManagedDedupeTask(id);
      if (action === 'delete') { await deleteManagedDedupeTask(id); navigate('/tasks'); return; }
      if (action === 'save') await updateDedupeTask(id, { interval_minutes: Number(interval) });
      toast.success('操作成功');
      refresh();
    } catch (error) { toast.error(error.response?.data?.error || '操作失败'); }
    finally { setBusy(false); }
  };
  const apply = async (ids) => {
    const chosen = choices.filter((finding) => ids.includes(finding.id));
    if (!chosen.length) return toast.error('请先勾选重复项或空目录');
    const scopeText = chosen.map((finding) => finding.path).join('\n');
    if (!window.confirm(`确认处理以下 ${chosen.length} 项？\n\n${scopeText}\n\n同名目录会合并；同名文件只保留最新一份，其余删除。空目录执行前确认仍为空就删除。`)) return;
    setBusy(true);
    try {
      await applyManagedDedupeTask(id, chosen.map((finding) => finding.id));
      toast.success('去重任务已开始；处理详情会写入去重日志');
      refresh();
    } catch (error) { toast.error(error.response?.data?.error || '启动去重失败'); }
    finally { setBusy(false); }
  };
  if (!task) return <div className="p-8 text-gray-500">正在读取去重任务…</div>;
  return <div className="max-w-6xl mx-auto space-y-5 pb-12">
    <div><Link to="/tasks" className="inline-flex items-center gap-2 text-sm text-blue-700"><ArrowLeft size={16} />返回任务管理</Link><h1 className="mt-3 text-xl font-bold break-all">{task.name}</h1><p className="mt-1 text-sm text-gray-500 break-all">{task.source_type === 'remote' ? `${task.remote}:${task.path}` : task.path}</p></div>
    <div className="bg-white rounded-xl border p-5 space-y-3">
      <div className="flex flex-wrap justify-between gap-3"><div><div className="font-medium">{task.mode === 'scheduled' ? '定时去重' : task.mode === 'check' ? '检查重复' : '一次性去重'} · {task.status === 'queued' ? '排队中' : task.status === 'scanning' ? '检查中' : task.status === 'ready' ? '检查完成，等待选择' : task.status === 'applying' ? '去重中' : task.status === 'idle' ? '待机' : task.status === 'complete' ? '已完成' : task.status === 'stopped' ? '已停止' : '异常'}</div><div className="text-xs text-gray-500 mt-1">{task.next_run ? `下次运行：${new Date(task.next_run).toLocaleString()}` : '无下次运行'} · {task.last_run ? `上次运行：${new Date(task.last_run).toLocaleString()}` : '尚未运行'}</div></div><button onClick={refresh} className="text-sm text-blue-700">刷新</button></div>
      {task.last_error && <div className="text-sm text-red-700 bg-red-50 p-3 rounded-lg break-all">{task.last_error}</div>}
      <div className="flex flex-wrap items-center gap-2">
        {running(task.status) ? <button onClick={() => act('stop')} disabled={busy} className="inline-flex items-center gap-1 px-3 py-2 rounded-lg bg-red-50 text-red-700"><Square size={16} />停止</button> : task.status !== 'ready' && task.status !== 'complete' && <button onClick={() => act('start')} disabled={busy} className="inline-flex items-center gap-1 px-3 py-2 rounded-lg bg-green-50 text-green-700"><Play size={16} />运行</button>}
        {task.mode === 'scheduled' && <><label className="text-sm">运行间隔（分钟）<input className="ml-2 w-24 rounded-lg border-gray-300" type="number" min="5" max="10080" value={interval ?? 60} onChange={(event) => setIntervalValue(event.target.value)} /></label><button onClick={() => act('save')} disabled={busy} className="px-3 py-2 rounded-lg bg-blue-50 text-blue-700">保存间隔</button></>}
        <button onClick={() => act('delete')} disabled={busy} className="inline-flex items-center gap-1 px-3 py-2 rounded-lg bg-gray-100 text-red-700"><Trash2 size={16} />删除任务</button>
        <Link to={`/logs?tab=dedupe&task_id=${id}`} className="px-3 py-2 rounded-lg bg-blue-50 text-blue-700 text-sm">查看每次去重日志</Link>
      </div>
      {task.mode !== 'scheduled' && task.status === 'complete' && <p className="text-xs text-gray-500">本次任务已完成。要再次检查，请从文件浏览器新建任务。</p>}
    </div>
    <form className="bg-white rounded-xl border p-4 flex flex-wrap items-center gap-3" onSubmit={(event) => { event.preventDefault(); openDirectory(jumpPath); }}>
      <label htmlFor="dedupe-jump-path" className="text-sm font-medium shrink-0">跳转目录</label>
      <input id="dedupe-jump-path" value={jumpPath} onChange={(event) => setJumpPath(event.target.value)} placeholder={task.path + '/子目录'} className="min-w-0 flex-1 rounded-lg border-gray-300 text-sm" />
      <button type="submit" className="px-3 py-2 rounded-lg bg-blue-600 text-white text-sm">跳转查看</button>
      <button type="button" onClick={() => openDirectory(task.path)} className="px-3 py-2 rounded-lg bg-blue-50 text-blue-700 text-sm">打开任务目录</button>
    </form>
    {task.mode === 'check' && <div className="bg-white rounded-xl border p-5 space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3"><h2 className="font-semibold">检查结果 · {choices.length} 个可独立处理项目</h2>{task.status === 'ready' && choices.length > 0 && <div className="flex flex-wrap items-center gap-3"><button onClick={() => setSelected(choices.map((finding) => finding.id))} className="text-sm text-blue-700">全选</button><button onClick={() => setSelected([])} className="text-sm text-blue-700">取消全选</button><span className="text-sm text-gray-500">已选 {selected.length} / {choices.length}{allSelected ? '（全部）' : ''}</span><button onClick={() => apply(selected)} disabled={busy || !selected.length} className="px-3 py-2 rounded-lg bg-amber-600 text-white disabled:opacity-50">去重选中项</button></div>}</div>
      {task.status === 'ready' && choices.length === 0 && <p className="text-sm text-green-700">未发现可去重项目。</p>}
      <div className="divide-y rounded-lg border">{choices.map((finding) => <div key={finding.id} className="flex items-center gap-3 px-3 py-2 text-sm">
        {task.status === 'ready' && <input type="checkbox" aria-label={`选择 ${finding.path}`} checked={selected.includes(finding.id)} onChange={() => setSelected((current) => current.includes(finding.id) ? current.filter((value) => value !== finding.id) : [...current, finding.id])} />}
        <button type="button" onClick={() => openDirectory(finding.path, finding.kind === 'merge' && finding.item_type === '同名文件')} title="在文件浏览器中查看，返回后继续处理" className="min-w-0 flex-1 break-all text-left text-blue-700 hover:underline inline-flex items-center gap-1"><span className="break-all">{finding.path}</span><ExternalLink size={13} className="shrink-0" /></button>
        <span className="shrink-0 text-gray-500">{finding.kind === 'empty' ? `空目录 ${finding.count} 个` : `${finding.item_type || '同名项目'} ${finding.count} 个`}</span>
        {task.status === 'ready' && <button onClick={() => apply([finding.id])} disabled={busy} className="text-amber-700 whitespace-nowrap">处理</button>}
      </div>)}</div>
    </div>}
    <div className="bg-white rounded-xl border p-5"><div className="flex items-center justify-between mb-3"><h2 className="font-semibold">当前任务日志</h2><Link to={`/logs?tab=dedupe&task_id=${id}`} className="text-sm text-blue-700">查看每次运行详情 →</Link></div><div className="bg-gray-950 text-gray-100 rounded-lg p-4 max-h-[500px] overflow-auto font-mono text-xs space-y-1">{(task.logs || []).length ? task.logs.map((line, index) => <div key={index} className="break-all">{line}</div>) : <div className="text-gray-400">等待任务开始…</div>}</div></div>
  </div>;
}
