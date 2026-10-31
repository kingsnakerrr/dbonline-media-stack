import React, { useEffect, useMemo, useState } from 'react';
import { AlertTriangle, CheckSquare, FolderSearch, RefreshCw } from 'lucide-react';
import toast from 'react-hot-toast';
import { applyDedupeSelection, getDedupeScan, getRemotes, startDedupeScan } from '../services/api';

const isRunning = (status) => status === 'scanning' || status === 'applying';
const canApply = (finding) => finding.kind === 'merge' || finding.kind === 'empty';

function Dedupe() {
  const [remotes, setRemotes] = useState([]);
  const [remote, setRemote] = useState('');
  const [directory, setDirectory] = useState('/');
  const [job, setJob] = useState(null);
  const [selected, setSelected] = useState([]);
  const [busy, setBusy] = useState(false);

  const refresh = async () => {
    try {
      const response = await getDedupeScan();
      setJob(response.data?.id ? response.data : null);
    } catch (error) {
      toast.error(error.response?.data?.error || '读取扫描状态失败');
    }
  };

  useEffect(() => {
    getRemotes().then((response) => {
      const names = response.data?.remotes || [];
      setRemotes(names);
      if (names.length) setRemote((value) => value || names[0]);
    }).catch(() => toast.error('读取 rclone 远端失败'));
    refresh();
  }, []);

  useEffect(() => {
    if (!isRunning(job?.status)) return undefined;
    const timer = setInterval(refresh, 2000);
    return () => clearInterval(timer);
  }, [job?.status]);

  const findings = job?.findings || [];
  const actionable = useMemo(() => findings.filter(canApply), [findings]);
  const allSelected = actionable.length > 0 && actionable.every((item) => selected.includes(item.id));

  const scan = async () => {
    if (!remote) return toast.error('请先选择远端');
    setBusy(true);
    try {
      const response = await startDedupeScan(remote, directory);
      setJob({ id: response.data.id, remote, path: directory, status: 'scanning', findings: [] });
      setSelected([]);
      toast.success('扫描已开始；此阶段不会修改文件');
    } catch (error) {
      toast.error(error.response?.data?.error || '启动扫描失败');
    } finally {
      setBusy(false);
    }
  };

  const apply = async (ids) => {
    const chosen = actionable.filter((item) => ids.includes(item.id));
    if (!chosen.length) return toast.error('请先选择项目');
    const scopes = chosen.filter((item) => item.kind === 'merge').map((item) => item.scope);
    const emptyCount = chosen.filter((item) => item.kind === 'empty').length;
    const confirmation = `确认处理 ${chosen.length} 项？\n\n远端：${job.remote}\n处理范围：${scopes.join('、') || '无'}\n空目录：${emptyCount} 个。\n\n同名目录会合并；同名文件只保留最新一份，其余删除。空目录执行前确认仍为空就删除。`;
    if (!window.confirm(confirmation)) return;
    setBusy(true);
    try {
      await applyDedupeSelection(job.id, ids, job.remote);
      setJob((current) => ({ ...current, status: 'applying' }));
      toast.success('已开始处理，可在此查看逐项结果');
    } catch (error) {
      toast.error(error.response?.data?.error || '启动处理失败');
    } finally {
      setBusy(false);
    }
  };

  const toggle = (id) => setSelected((current) => current.includes(id) ? current.filter((value) => value !== id) : [...current, id]);
  const ready = job?.status === 'ready';

  return (
    <div className="max-w-6xl mx-auto space-y-6 pb-12">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">云盘去重与空目录整理</h1>
        <p className="mt-1 text-sm text-gray-500">先扫描预览，再按目录范围单独处理或全选处理。扫描不会移动或删除任何文件。</p>
      </div>

      <div className="bg-white rounded-xl border border-gray-200 p-5 space-y-4">
        <div className="grid gap-4 md:grid-cols-[240px_1fr_auto] items-end">
          <label className="text-sm font-medium text-gray-700">Rclone 远端
            <select value={remote} onChange={(event) => setRemote(event.target.value)} className="mt-1 block w-full rounded-lg border-gray-300">
              {remotes.map((name) => <option key={name} value={name}>{name}</option>)}
            </select>
          </label>
          <label className="text-sm font-medium text-gray-700">扫描目录
            <input value={directory} onChange={(event) => setDirectory(event.target.value)} placeholder="/电影" className="mt-1 block w-full rounded-lg border-gray-300" />
          </label>
          <button onClick={scan} disabled={busy || isRunning(job?.status)} className="inline-flex items-center justify-center gap-2 px-5 py-2.5 rounded-lg bg-blue-600 text-white disabled:opacity-50 hover:bg-blue-700">
            <FolderSearch size={18} /> 扫描重复项
          </button>
        </div>
        <div className="flex gap-2 text-amber-800 bg-amber-50 border border-amber-200 rounded-lg p-3 text-sm">
          <AlertTriangle className="shrink-0" size={18} />
          <span>同名目录合并；同名文件只保留最新一份。空目录执行前确认仍为空就清理。请先核对路径再处理。</span>
        </div>
      </div>

      {job && <div className="bg-white rounded-xl border border-gray-200 p-5 space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <div className="font-semibold text-gray-900">{job.remote}:{job.path} · {job.status === 'scanning' ? '扫描中' : job.status === 'ready' ? '等待选择' : job.status === 'applying' ? '处理中' : job.status === 'complete' ? '处理完成' : job.status === 'partial_failure' ? '部分失败' : '扫描失败'}</div>
            <div className="text-sm text-gray-500 mt-1">同名目录/文件范围 {findings.filter((item) => item.kind === 'merge').length} 个，空目录 {findings.filter((item) => item.kind === 'empty').length} 个</div>
          </div>
          <button onClick={refresh} className="inline-flex items-center gap-1 text-blue-700 text-sm"><RefreshCw size={16} />刷新状态</button>
        </div>
        {isRunning(job.status) && <div className="text-sm text-blue-700">后台运行中；目录较多时需要几分钟，页面会自动刷新。</div>}
        {job.error && <div className="text-sm text-red-700 bg-red-50 p-3 rounded-lg">{job.error}</div>}
        {job.status === 'ready' && actionable.length > 0 && <div className="flex flex-wrap items-center gap-3 border-t pt-4">
          <button onClick={() => setSelected(allSelected ? [] : actionable.map((item) => item.id))} className="inline-flex items-center gap-2 text-sm text-blue-700"><CheckSquare size={17} />{allSelected ? '取消全选' : '全选可处理项目'}</button>
          <span className="text-sm text-gray-500">已选 {selected.length} / {actionable.length}</span>
          <button onClick={() => apply(selected)} disabled={!selected.length || busy} className="px-4 py-2 rounded-lg bg-amber-600 text-white disabled:opacity-50 hover:bg-amber-700">处理选中项目</button>
        </div>}
        {job.status === 'ready' && findings.length === 0 && <div className="text-sm text-green-700 bg-green-50 p-4 rounded-lg">此目录未发现重复项或空目录。</div>}
      </div>}

      {actionable.length > 0 && <div className="bg-white rounded-xl border border-gray-200 divide-y divide-gray-100 overflow-hidden">
        {actionable.map((finding) => <div key={finding.id} className="flex items-center gap-3 px-4 py-2 text-sm">
          {ready && <input type="checkbox" checked={selected.includes(finding.id)} onChange={() => toggle(finding.id)} aria-label={`选择 ${finding.path}`} />}
          <span className="min-w-0 flex-1 break-all">{finding.path}</span>
          <span className="shrink-0 text-gray-500">{finding.kind === 'empty' ? `空目录 ${finding.count} 个` : `${finding.item_type || '同名项目'} ${finding.count} 个`}</span>
          {ready && <button onClick={() => apply([finding.id])} disabled={busy} className="text-amber-700 whitespace-nowrap">处理</button>}
        </div>)}
      </div>}
      {job?.log?.length > 0 && <div className="bg-white rounded-xl border border-gray-200 p-5"><h2 className="font-semibold mb-3">处理记录</h2><div className="space-y-2 text-sm text-gray-700">{job.log.map((line, index) => <div key={index} className="break-all">{line}</div>)}</div></div>}
    </div>
  );
}

export default Dedupe;
