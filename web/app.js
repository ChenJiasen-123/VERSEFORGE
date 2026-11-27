const $ = id => document.getElementById(id);
const state = {csrf: null, busy: false, poem: null, job: null, poll: null, configured: false};
const samples = {
 object: '题画绝句：为一件日常器物题诗\n要求：五绝或七绝一首，须在诗题中标注所题器物；诗中不得出现该器物的名称，只能写其形、声、用、痕。',
 future: '写给十年后的自己，但那时AI已替你回信\n要求：写一首诗，不超过30行；诗中包含你写给十年后自己的一句话和一个自动回复/系统提示的片段（可以是短信、邮件退信、AI助手提醒），两者不得互相解释。'
};
const phases = {queued:'已排队，正在等候创作', planning:'正在辨认要求，展开不同构思', writing:'正在写作', checking:'正在核对题目要求', revising:'正在调整与要求冲突的部分'};
async function api(path, options = {}) {
 const response = await fetch(path, {...options, headers: {'Content-Type':'application/json', ...(state.csrf ? {'X-CSRF-Token':state.csrf} : {}), ...(options.headers || {})}});
 const data = await response.json();
 if (!response.ok) throw new Error(data.error || '本地服务暂时没有回应。');
 return data;
}
function count() {$('input-count').textContent = `${$('prompt').value.length} 字`;}
function setBusy(busy, phase = '') {
 state.busy = busy; $('generate').disabled = busy || !state.configured;
 $('again').disabled = busy || !state.poem || !state.configured;
 $('progress').hidden = !busy; $('progress-text').textContent = phases[phase] || '正在创作';
 $('generate').textContent = busy ? '创作中，请稍候' : '生成一版作品';
}
function error(message) {$('error').textContent=message; $('error').hidden=!message;}
function list(id, rows) {
 $(id).replaceChildren(...(rows.length ? rows : ['无特别指定。']).map(text => {const node=document.createElement('li');node.textContent=text;return node;}));
}
function render(job) {
 const result=job.result;
 if (!result || result.status==='unsupported') {state.poem=null;$('poem').hidden=true;$('expansion-card').hidden=true;$('empty').hidden=false;$('understanding').hidden=true;$('style-review').hidden=true;$('meter-review').hidden=true;$('copy').disabled=$('download').disabled=$('again').disabled=true;error(result?.message || job.error || '没有得到作品。');return;}
 state.poem=result.poem; state.job=job.id;
 $('empty').hidden=true; $('poem').hidden=false;
 const expOut=result.expansion_output;
 if (expOut && expOut.enabled && expOut.adopted_anchor) {
  $('expansion-card').hidden=false;
  $('expansion-meta').textContent=`模型：${expOut.model || 'deepseek-reasoner'} · 采纳支点 #${(expOut.selected_index || 0)+1}`;
  const fields=[['起跳切口',expOut.adopted_anchor.entry_anchor],['尺度关系',expOut.adopted_anchor.world_scale],['发话姿态',expOut.adopted_anchor.stance_and_relation],['推进转折',expOut.adopted_anchor.arc_turn],['避俗边界',expOut.adopted_anchor.avoid]];
  const nodes=[];
  for (const [label,val] of fields) {
   if (!val) continue;
   const dt=document.createElement('dt');dt.textContent=label;
   const dd=document.createElement('dd');dd.textContent=val;
   nodes.push(dt,dd);
  }
  $('expansion-grid').replaceChildren(...nodes);
  const others=(expOut.all_anchors || []).map((a,i)=>({a,i})).filter(x=>x.i!==expOut.selected_index && x.a?.entry_anchor);
  $('other-anchors-wrap').hidden=!others.length;
  if (others.length) {
   list('other-anchors', others.map(x=>`备选 #${x.i+1}：${x.a.entry_anchor}｜${x.a.world_scale}｜${x.a.arc_turn}`));
  }
 } else {
  $('expansion-card').hidden=true;
 }
 $('poem-title').textContent=result.poem.title;
 $('poem-lines').replaceChildren(...result.poem.lines.map(text => {
  if (!text) {const gap=document.createElement('div');gap.className='stanza-gap';gap.setAttribute('aria-hidden','true');return gap;}
  const p=document.createElement('p');p.textContent=text;return p;
 }));
 $('copy').disabled=false; $('download').disabled=false; $('again').disabled=state.busy || !state.configured;
 $('saved').textContent='已保存至本机';
 const brief=result.brief;
 if (brief) {
  $('understanding').hidden=false;list('requirements',brief.requirements || []);list('optional-examples',brief.examples || []);
  const dirs=(brief.directions || []).map((d,i)=>(i===brief.selected_direction?'【主选方向 '+(i+1)+'】':'【候选方向 '+(i+1)+'】')+d);
  list('all-directions',dirs);
  $('direction').textContent='首候选出发方向：'+(brief.directions?.[brief.selected_direction] || '');
 }
 const se=result.style_engine;
 $('style-review').hidden=!se;
 if (se) {
  if (se.mode==='rpe_v4' && se.final_diagnostics) {
   const fd=se.final_diagnostics;
   const expLabels={expand_v1:'开启 RPE-GA 诗学扩写',none:'关闭（原题直出）'};
   const ver=se.prompt_version || 'v6';
   const thinkTag=se.generation_thinking==='enabled'?' + Thinking':'';
   const polishTag=result.editorial?' · 自动打磨：开启':' · 自动打磨：关闭';
   $('style-summary').textContent=`前置扩写：${expLabels[se.expansion_mode] || '开启 RPE-GA 诗学扩写'}${se.expansion_mode==='none'?'':`（${se.expansion_model || 'deepseek-reasoner'}）`} · 写诗引擎：RPE-GA ${ver}${thinkTag}（${se.prompt_id}）${polishTag} · 终稿风格分 ${fd.score.toFixed(2)} / 100`;
   const coreNote=fd.core_motif_span!=null?` · 主核贯通 ${(fd.core_motif_span*100).toFixed(0)}%`:'';
   const items=[
    `终稿结构与呼吸：${fd.stanza_count} 节 ${fd.line_count} 行 · 无标点断行率 ${(fd.unpunctuated_break_rate*100).toFixed(0)}% · 行内空格率 ${(fd.mid_line_space_rate*100).toFixed(0)}%${coreNote}`,
    `分项计量：语料分位带对齐 ${fd.corpus_band_score.toFixed(2)} · 词域共鸣 ${fd.tfidf_lexical_score.toFixed(2)} · 反套路扣分 ${fd.anti_slop_penalty.toFixed(2)}`,
   ];
   if (fd.attribution?.label) items.push(`外部三诗人语料近邻归属：${fd.attribution.label}（投票占比 ${(fd.attribution.confidence*100).toFixed(1)}%）`);
   (se.candidates || []).forEach(c => {
    if (c.style_v4_score != null) items.push(`初稿候选 ${c.candidate}${c.candidate===se.selected_candidate?'（胜出）':''}：《${c.title || '无题'}》 · v4 风格分 ${c.style_v4_score.toFixed(2)} · 方向：${c.direction}`);
   });
   (fd.anti_slop_flags || []).forEach(f => items.push(`反套路提示：${f.detail}（-${f.penalty}）`));
   list('style-details', items);
  } else {
   $('style-summary').textContent=se.note || '标准流程模式';
   list('style-details', []);
  }
 }
 const checks=result.checks || {};
 const meter=checks.final_meter;
 const classical=result.task?.genre && result.task.genre!=='modern';
 $('meter-review').hidden=!(meter || classical);
 const meterLabels={pass:'当前基本谱检查通过，尚未认证语境核音或完整合律。',unknown:'仍有核音或韵部未确定项。',failed:'发现与当前基本谱冲突的项目。'};
 $('meter-summary').textContent=meter ? (meterLabels[meter.report.status] || '结果仍需核对。') : '这份历史记录没有保存逐项格律证据。';
 const kinds={rhyme:'韵脚',shape:'句数或字数',ambiguous_reading:'多音待核',missing_reading:'缺少核音依据',incomplete_glyph_candidates:'字形候选证据不全',tone:'平仄'};
 $('meter-findings').replaceChildren(...(meter?.report.findings || []).filter(row=>row.status==='unknown' || row.status==='failed').map(row=>{
  const li=document.createElement('li');
  const location=row.line ? `第${row.line}句第${row.character}字「${row.text}」` : (row.positions || []).map(p=>`第${p.line}句「${p.text}」`).join('、');
  li.textContent=(row.status==='failed'?'冲突':'待核')+' · '+(kinds[row.kind] || '规则核对')+(location?'：'+location:'');
  return li;
 }));
 const report=checks.final_requirement_report;
 $('requirement-review').hidden=!report;
 const labels={satisfied:'已找到依据',violated:'存在冲突',uncertain:'待确认',not_required:'并非硬要求'};
 $('requirement-evidence').replaceChildren(...(report?.checks || []).map(row=>{
  const li=document.createElement('li');
  const heading=document.createElement('p');heading.textContent=(labels[row.status] || '待确认')+' · '+row.requirement;
  const evidence=document.createElement('p');evidence.className='small muted';
  evidence.textContent=row.evidence ? '作品引文：'+row.evidence : row.reason;
  if(row.evidence_issue) evidence.textContent+='（这项依据仍需确认）';
  li.append(heading,evidence);return li;
 }));
 if(report && !report.checks?.length){const li=document.createElement('li');li.textContent='这次核对未完整返回，作品已保留。';$('requirement-evidence').append(li);}
 const pending=(checks.final_hard_issues?.length || 0)>0 || checks.revision_semantics_rechecked===false || checks.requirements_confirmed===false;
 const parallelPending=checks.parallelism_status==='unknown';
 const meterPending=meter ? meter.report.status!=='pass' : classical;
 $('result-note').hidden=!(pending || parallelPending || meterPending);
 $('result-note').textContent=pending?'这版已生成。部分题目要求仍需确认，可展开题目理解或再换一个构思。':'';
 if(parallelPending) $('result-note').textContent+=' 律诗中间两联的对仗仍需人工核对。';
 if(meterPending) $('result-note').textContent+=' 平仄或押韵仍需核对，可展开逐项结果查看。';
 const editorial=result.editorial;
 if(editorial){
  if(editorial.rounds){
   const end={editor_keep:'编辑判断可保留',round_limit:'达到轮数上限',budget_exhausted:'达到编辑预算上限'};
   $('result-note').hidden=false;
   $('result-note').textContent+=' 自动打磨完成 '+editorial.rounds.length+' 轮，'+(end[editorial.status] || '编辑结束')+'；'+(editorial.adopted?'已采用修订稿。':'保留进入打磨前的版本。');
   return;
  }
  const notices={revision_selected:'独立审稿后采用了修订稿，仍可自行判断文字。',no_revision_requested:'独立审稿未建议修改。',revision_constraints_unconfirmed:'修订稿的题目要求尚未确认，保留编辑前版本。',revision_still_needs_editing:'修订稿仍有待修改之处，保留编辑前版本。',original_retained:'比较未支持替换，保留编辑前版本。',editor_incomplete:'独立审稿未完整完成，保留编辑前版本。'};
  $('result-note').hidden=false;
  $('result-note').textContent+=' '+(notices[editorial.status] || '独立审稿结果已记录。');
 }
}
async function history() {
 const rows=await api('/api/jobs');
 for (const target of ['history','mobile-history']) {
  $(target).replaceChildren();
  if (!rows.length) {const p=document.createElement('p');p.className='muted small';p.textContent='第一首诗，正等着一个题目。';$(target).append(p);}
  for (const row of rows) {
   const button=document.createElement('button');button.type='button';button.className='history-item';
   const title=document.createElement('strong');title.textContent=row.title || row.prompt.split('\n')[0].slice(0,42);
   const meta=document.createElement('span');meta.textContent=new Date(row.created*1000).toLocaleString('zh-CN',{month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'})+' · '+(row.status==='completed'?'已保存':row.status==='failed'?'未完成':'创作中');
   button.append(title,meta);button.addEventListener('click',async()=>{if(state.busy)return;error('');try {const job=await api('/api/jobs/'+row.id);$('prompt').value=job.prompt;$('genre').value=job.request?.genre || 'modern';$('expansion-mode').value=job.request?.expansion_mode==='none'?'none':'expand_v1';$('expansion-model').value=(job.request?.expansion_model==='default'?'deepseek-flash':job.request?.expansion_model) || 'deepseek-reasoner';syncExpansionField();$('style-mode').value=(job.request?.style_mode==='rpe_v4'?'rpe_v6':job.request?.style_mode) || 'rpe_v6';$('auto-polish').value=job.request?.auto_polish==='on'?'on':'off';$('preference').value=job.request?.preference || '';count();if(job.status==='completed')render(job);else if(job.status==='failed')error(job.error);else {state.job=job.id;setBusy(true,job.status);poll(job.id);}}catch(e){error(e.message);}});$(target).append(button);
  }
 }
}
async function poll(id) {
 try {
  const job=await api('/api/jobs/'+id);
  if(job.status==='completed' || job.status==='failed') {setBusy(false);if(job.status==='completed')render(job);else error(job.error);await history();return;}
  setBusy(true,job.status);state.poll=setTimeout(()=>poll(id),1200);
 }catch(e){setBusy(false);error(e.message+' 作品记录保留在本机，刷新后可继续查看。');}
}
function syncExpansionField() {$('expansion-model-field').hidden = $('expansion-mode').value === 'none';}
$('expansion-mode').addEventListener('change', syncExpansionField);
syncExpansionField();
async function generate(previous = null) {
 if(state.busy)return;
 if(!$('compose-form').reportValidity())return;
 error('');setBusy(true,'queued');$('saved').textContent='';
 try {const job=await api('/api/jobs',{method:'POST',body:JSON.stringify({prompt:$('prompt').value,genre:$('genre').value,expansion_mode:$('expansion-mode').value,expansion_model:$('expansion-model').value,style_mode:$('style-mode').value,auto_polish:$('auto-polish').value,preference:$('preference').value,previous})});state.job=job.id;await history();await poll(job.id);}
 catch(e){setBusy(false);error(e.message);}
}
function plainText() {return state.poem ? state.poem.title+'\n\n'+state.poem.lines.join('\n') : '';}
$('compose-form').addEventListener('submit',e=>{e.preventDefault();generate();});
$('again').addEventListener('click',()=>generate(state.poem));
$('prompt').addEventListener('input',count);
document.querySelectorAll('[data-example]').forEach(button=>button.addEventListener('click',()=>{if(state.busy)return;$('prompt').value=samples[button.dataset.example];count();$('prompt').focus();}));
$('copy').addEventListener('click',async()=>{try{await navigator.clipboard.writeText(plainText());$('saved').textContent='已复制作品';}catch{error('浏览器暂未允许复制，可选中文字复制，或下载文字。');}});
$('download').addEventListener('click',()=>{const url=URL.createObjectURL(new Blob([plainText()],{type:'text/plain;charset=utf-8'}));const a=document.createElement('a');a.href=url;a.download=state.poem.title.replace(/[<>:"/\\|?*]/g,'_')+'.txt';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);});
$('new').addEventListener('click',()=>{if(state.busy)return;state.poem=null;$('prompt').value='';$('preference').value='';count();$('poem').hidden=true;$('expansion-card').hidden=true;$('empty').hidden=false;$('understanding').hidden=true;$('style-review').hidden=true;$('meter-review').hidden=true;$('result-note').hidden=true;$('saved').textContent='';$('copy').disabled=$('download').disabled=$('again').disabled=true;error('');$('prompt').focus();});
(async()=>{try{const session=await api('/api/session');state.csrf=session.csrf;state.configured=session.configured;$('connection').textContent=session.configured?'本地创作服务已就绪':'创作服务尚未配置';$('connection').classList.toggle('ready',session.configured);setBusy(false);await history();}catch(e){state.configured=false;setBusy(false);$('connection').textContent='本地服务未连接';error(e.message);}})();
