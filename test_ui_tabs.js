#!/usr/bin/env node
// 组卡页页签逻辑回归：用 DOM 桩 + 假后端把 index.html 的脚本在 node 里真跑一遍。
// 覆盖：职业页签 / 「通用」只过滤浏览不影响卡组归属 / 换职业清空卡组 /
//       开局时 cls 用卡组职业而不是当前浏览页。
// 用法：node test_ui_tabs.js   （改了组卡页交互就跑一下）
const fs = require('fs'); const vm = require('vm');
const elems = {};
function mkEl(id){ return {
  id, textContent:'', innerHTML:'', value:'', disabled:false, title:'', dataset:{},
  classList:{ _s:new Set(),
    add(c){this._s.add(c)}, remove(c){this._s.delete(c)},
    toggle(c,v){ if(v===undefined){ this._s.has(c)?this._s.delete(c):this._s.add(c);} else { v?this._s.add(c):this._s.delete(c);} return this._s.has(c); },
    contains(c){return this._s.has(c)} },
  children:[], appendChild(ch){this.children.push(ch)}, addEventListener(){}, options:[],
};}
global.document = {
  getElementById(id){ return elems[id] || (elems[id]=mkEl(id)); },
  querySelectorAll(sel){ return sel.startsWith('#clsTabs') ? (elems['clsTabs']?.children||[]) : []; },
  createElement(tag){ return mkEl(tag); },
};
global.location = { search:'' }; global.window = global;

const CARDS=[
 {cid:'VAN_CS2_029',name:'火球术',cost:4,type:'SPELL',text:'',rarity:'FREE',cls:'MAGE',ok:true,partial:false},
 {cid:'VAN_EX1_019',name:'灵魂之火',cost:0,type:'SPELL',text:'',rarity:'FREE',cls:'NEUTRAL',ok:true,partial:false},
 {cid:'VAN_CS2_106',name:'炽炎战斧',cost:2,type:'WEAPON',text:'',rarity:'FREE',cls:'WARRIOR',ok:true,partial:false},
];
const CLASSES=[{id:'MAGE',name:'法师'},{id:'WARLOCK',name:'术士'},{id:'HUNTER',name:'猎人'}];
global.__started = null;
const baseFetch = async (path, opt)=>{
  if(path.startsWith('/api/cards')){
    const cls = decodeURIComponent(path.split('cls=')[1]||'');
    const cards = CARDS.filter(c => cls==='NEUTRAL' ? c.cls==='NEUTRAL' : (c.cls===cls || c.cls==='NEUTRAL'));
    return { ok:true, json:async()=>({ok:true, cards, classes:CLASSES, hero_powers:{}}) };
  }
  if(path.startsWith('/api/start')){
    const st = { me:{name:'我',cls:'WARLOCK',hp:30,mana:1,max_mana:1,hand:[],board:[],deck:20,
                     hero_name:'我',hero_power_used:false,hero_atk:0},
                 foe:{name:'AI',cls:'MAGE',hp:30,mana:0,max_mana:0,hand:[],board:[],deck:20,
                      hero_name:'AI',hero_power_used:false,hero_atk:0},
                 log:[], over:false, cur:0, timer:0 };
    return { ok:true, json:async()=>({ok:true, seed:1, state:st, hp_used:false}) };
  }
  if(path.startsWith('/api/state'))
    return { ok:false, status:400, json:async()=>({ok:false, error:{code:'no_game', message:'x'}}) };
  throw new Error('unexpected path: '+path);
};
global.fetch = new Proxy(baseFetch, { apply(t, thisArg, [path, opt]){
  if(path.startsWith('/api/start') && opt && opt.body){ global.__started = JSON.parse(opt.body); }
  return Reflect.apply(t, thisArg, [path, opt]);
}});
global.__sleep = ms => new Promise(r=>setTimeout(r, ms));
global.__A = (cond,msg)=>{ console.log((cond?'  ✓ ':'  ✗ ')+msg); if(!cond) process.exitCode=1; };

const SRC = fs.readFileSync('static/index.html','utf-8');
const JS = SRC.match(/<script>([\s\S]*)<\/script>/)[1];
vm.runInThisContext(JS, {filename:'static/index.html#script'});

const checks = `(async ()=>{
  const sleep = global.__sleep, A = global.__A;
  await sleep(30);
  const tabs = document.getElementById('clsTabs').children;
  A(tabs.length===4, '页签 3 职业 + 通用（实际：' + tabs.map(t=>t.textContent).join(',') + '）');
  A(DECKCLASS==='MAGE' && VIEWCLS==='MAGE', '初始为法师');
  A(document.getElementById('pool').innerHTML.includes('k-MAGE'),
    '职业页里职业牌带职业色标');
  A(document.getElementById('pool').innerHTML.includes('k-NEUTRAL'),
    '职业页里中立牌也带「中立」色标');

  pickTab('NEUTRAL'); await sleep(20);
  A(VIEWCLS==='NEUTRAL' && DECKCLASS==='MAGE', '切通用后卡组职业不变');
  A(ALL.length===1 && ALL[0].name==='灵魂之火', '通用页只显示中立牌（' + ALL.map(c=>c.name) + '）');
  add('VAN_EX1_019'); await sleep(5);
  A(DECK.length===1, '通用页可以把中立牌加进卡组');

  pickTab('WARLOCK'); await sleep(20);
  A(DECKCLASS==='WARLOCK' && VIEWCLS==='WARLOCK' && DECK.length===0, '换职业清空卡组');
  add('VAN_EX1_019'); await sleep(5);
  A(DECK.length===1, '术士页加灵魂之火');

  pickTab('NEUTRAL'); await sleep(20);
  A(DECK.length===1 && VIEWCLS==='NEUTRAL', '回通用页卡组保留');

  await startGame(); await sleep(5);
  A(global.__started && global.__started.cls==='WARLOCK' && global.__started.deck.length===1,
    '开局 cls 用卡组职业（实际 ' + (global.__started && global.__started.cls) + '）');
  A(document.getElementById('viewDeck').classList.contains('hidden') &&
    !document.getElementById('viewGame').classList.contains('hidden'), '开局后切到对战视图');

  console.log(process.exitCode ? '结果：有失败项' : '结果：页签逻辑全部通过');
})().catch(e=>{ console.error('挂了：', e); process.exit(1); });`;

vm.runInThisContext(checks, {filename:'/tmp/checks.js'});
