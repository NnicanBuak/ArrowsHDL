// Run the delivered HTML's own script without browser or network dependencies.
// Exercise net selection, ancestry filters, canvas rendering and core/full fit.
import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';

const html=fs.readFileSync(process.argv[2],'utf8');
const data=JSON.parse(html.match(/<script id="data" type="application\/json">([\s\S]*?)<\/script>/)[1]);
const script=html.match(/<script>\s*([\s\S]*?)<\/script>/)[1];
let strokes=0,icons=0,strokeColors=[],usedSprites=[];
const ctx=new Proxy({measureText:s=>({width:s.length*8}),stroke:()=>{strokes++;strokeColors.push(ctx.strokeStyle)},drawImage:img=>{icons++;usedSprites.push(img.url)}},
                    {get:(t,k)=>k in t?t[k]:(()=>{})});
class Element {
  constructor(id){this.id=id;this.value=id==='mode'?'nets':'';this.textContent='';this.innerHTML='';this.options=[];this.children=[];this.classList={add(){},remove(){}}}
  add(option){this.options.push(option)} append(item){this.children.push(item)}
  replaceChildren(...items){this.options=items;this.value=''}
}
const elements=new Map();
for(const id of ['map','title','metrics','mode','bus','bit','core','full','clear','legend','ports','detail','status','data','modules','physical','modulefilter','physical-view','module-view','module-overview','sheets'])elements.set(id,new Element(id));
Object.assign(elements.get('map'),{clientWidth:1100,clientHeight:640,parentElement:{},getContext:()=>ctx,addEventListener(){},getBoundingClientRect:()=>({left:0,top:0}),setPointerCapture(){}});
elements.get('data').textContent=JSON.stringify(data);
const sandbox={document:{getElementById:id=>elements.get(id),createElement:()=>new Element('p')},devicePixelRatio:1,
 Option:class{constructor(label,value){this.label=label;this.value=value}},
 Image:class{set src(value){this.url=value;queueMicrotask(()=>this.onload())}},ResizeObserver:class{constructor(fn){this.fn=fn}observe(){this.fn()}}};
const context=vm.createContext(sandbox);
new vm.Script(script).runInContext(context);
await new Promise(resolve=>setImmediate(resolve));
assert.equal(vm.runInContext('ready',context),true);
assert(icons>0&&strokes>0,'Actual canvas draw functions must run');
elements.get('core').onclick();
const initial=vm.runInContext('scale',context);
elements.get('full').onclick();
const full=vm.runInContext('scale',context);
if(data.core?.cells)assert(full<=initial,'Full-map fit should include port tails');
elements.get('core').onclick();
assert.equal(vm.runInContext('scale',context),initial);
if(data.buses.length){
 strokeColors=[];usedSprites=[];
 elements.get('mode').value='routing';elements.get('mode').onchange();
 assert.match(elements.get('legend').innerHTML,/Source/);
 assert.equal(new Set(data.sources.map(s=>s.color)).size,data.sources.length,'Every source has its own colour');
 const originals=new Set(Object.values(data.sprites));
 assert(usedSprites.every(url=>originals.has(url)),'Original arrow colours must remain intact');
 assert(vm.runInContext('nets.every(n=>colors(n).length===1)',context),'No mixed colours after gates');
 assert(data.markers.every(m=>m.type===(m.kind==='inputs'?22:23)),'Source/Target markers identify I/O');
 elements.get('bus').value=data.buses[0].name;elements.get('bus').onchange();
 assert.equal(elements.get('bit').options.length,data.buses[0].bits.length+1);
 elements.get('bit').value=String(data.buses[0].bits[0]);elements.get('bit').onchange();
 const count=vm.runInContext('nets.filter(highlight).length',context);assert(count>0&&count<netsLength());
 const source=data.sources[0];
 vm.runInContext(`chooseSource(${JSON.stringify(source.id)})`,context);
 assert.equal(vm.runInContext('selected.size',context),0,'Source tracing must cross net boundaries');
 assert.equal(elements.get('bit').value,String(source.bit));
 assert(vm.runInContext('nets.filter(highlight).every(n=>colors(n).length===1)',context));
 elements.get('clear').onclick();
 assert.equal(vm.runInContext('nets.filter(highlight).length',context),data.nets.length);
 elements.get('mode').value='nets';elements.get('mode').onchange();
}
function netsLength(){return data.nets.length}
const gate=data.cells.find(c=>c.gate&&!c.gate.id.startsWith('port:'));
if(gate){
 vm.runInContext(`showCell(byPos.get(${JSON.stringify(gate.at.join(','))}))`,context);
 assert.match(elements.get('detail').innerHTML,/Входные сигналы/);
 assert(vm.runInContext('selected.size',context)>1);
}
const wire=data.cells.find(c=>!c.gate);
vm.runInContext(`showCell(byPos.get(${JSON.stringify(wire.at.join(','))}))`,context);
assert.match(elements.get('detail').innerHTML,/Физические выходы/);
assert.equal(vm.runInContext('selected.size',context),1);
if(data.modules.length){
 elements.get('modules').onclick();
 assert.equal(vm.runInContext('moduleMode',context),true);
 assert.match(elements.get('sheets').innerHTML,/module-sheet/);
 for(const m of data.modules)assert(elements.get('module-overview').innerHTML.includes(m.id));
 elements.get('modulefilter').value=data.modules[0].id;elements.get('modulefilter').onchange();
 assert.match(elements.get('sheets').innerHTML,/open/);
 elements.get('clear').onclick();
}
elements.get('mode').value='values';elements.get('mode').onchange();
assert(vm.runInContext("nets.every(n=>valueOf(n.id)===0||valueOf(n.id)===1)",context));
let arithmetic=0;
if(data.top==='mul4'){
 for(let a=0;a<16;a++)for(let b=0;b<16;b++){
  for(const s of data.sources)vm.runInContext(`sourceStates.set(${JSON.stringify(s.net)},${((s.bus==='a'?a:b)>>s.bit)&1});memo.clear()`,context);
  const actual=data.markers.filter(m=>m.kind==='outputs').reduce((total,m)=>total+(vm.runInContext(`valueOf(${JSON.stringify(data.nets[m.net].id)})`,context)<<Number(m.label.match(/\[(\d+)\]/)[1])),0);
  assert.equal(actual,a*b);arithmetic++;
 }
}
if(data.top==='adder8'){
 for(const[a,b,cin]of[[0,0,0],[255,0,1],[255,255,1],[85,170,0],[127,1,0],[0,0,1]]){
  for(const s of data.sources){const v=s.bus==='a'?a:s.bus==='b'?b:cin;vm.runInContext(`sourceStates.set(${JSON.stringify(s.net)},${(v>>s.bit)&1});memo.clear()`,context)}
  let sum=0,cout=0;
  for(const m of data.markers.filter(m=>m.kind==='outputs')){const value=vm.runInContext(`valueOf(${JSON.stringify(data.nets[m.net].id)})`,context);if(m.label.startsWith('sum['))sum+=value<<Number(m.label.match(/\[(\d+)\]/)[1]);else cout=value}
  assert.equal(sum+cout*256,a+b+cin);arithmetic++;
 }
}
console.log(JSON.stringify({passed:true,top:data.top,cells:data.cells.length,nets:data.nets.length,sources:data.sources.length,markers:data.markers.length,modules:data.modules.map(m=>m.id),arithmetic_vectors:arithmetic,drawn_icons:icons,checks:['script','draw','core/full','unique source colours','original sprites','Source/Target','no mixed colours','module sheets','gate values','source tracing','operator inputs/output']}));
