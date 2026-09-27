// PENDING / NOT EXECUTED. Run through use_figma after quota is available.
// Required skills: figma-use, figma-generate-library, figma-generate-design.
// File: nbbKLI3KZ3GeQlUDFx24tT. Inspect IDs first; do not create another file.
// This is a preview-only Inter substitution. Native SwiftUI remains system SF Pro.
// Brand migration is PENDING: the online file is still named SkyCompanion until this runs.
// After this flow-page repair, run figma-brand-migration.js once per remaining page.
const page=await figma.getNodeByIdAsync('0:1');
await figma.setCurrentPageAsync(page);
await Promise.all(['Regular','Semi Bold','Bold'].map(style=>figma.loadFontAsync({family:'Inter',style})));
for(const style of await figma.getLocalTextStylesAsync()){
  const weight=style.fontName.style;
  style.fontName={family:'Inter',style:weight==='Semibold'?'Semi Bold':weight};
  style.name=style.name.replace(/\bSkyCompanion\b/g,'SkyCompanion');
}
figma.root.name='SkyCompanion — On-device iPhone Companion';
for(const collection of await figma.variables.getLocalVariableCollectionsAsync()){
  collection.name=collection.name.replace(/\bSkyCompanion\b/g,'SkyCompanion');
}
for(const node of page.query('*')){
  node.name=node.name.replace(/\bSkyCompanion\b/g,'SkyCompanion');
  if(node.type==='TEXT') node.characters=node.characters.replace(/\bSkyCompanion\b/g,'SkyCompanion');
}
const screens={
  "Setup": {
    "id": "6:6",
    "width": 430,
    "height": 932
  },
  "Home": {
    "id": "6:29",
    "width": 430,
    "height": 932
  },
  "Drone": {
    "id": "6:48",
    "width": 430,
    "height": 932
  },
  "Session": {
    "id": "6:68",
    "width": 430,
    "height": 932
  },
  "Video": {
    "id": "6:92",
    "width": 430,
    "height": 932
  },
  "Settings": {
    "id": "6:110",
    "width": 430,
    "height": 932
  },
  "Diagnostics": {
    "id": "6:133",
    "width": 430,
    "height": 932
  },
  "Dark home": {
    "id": "6:153",
    "width": 430,
    "height": 932
  }
};
const oldBoard=await figma.getNodeByIdAsync('6:2');
let i=0;
for(const [name,info] of Object.entries(screens)){
  const frame=await figma.getNodeByIdAsync(info.id);
  if(!frame||frame.type!=='FRAME')throw Error('Missing screen '+info.id);
  page.appendChild(frame);
  frame.x=112+(i%4)*454; frame.y=224+Math.floor(i/4)*980;
  frame.name=name+' · Preview Inter; SwiftUI system font';
  frame.annotations=[{label:'Preview uses Inter because SF Pro does not render in the MCP service. App uses native system font. VoiceOver order: heading, state, grouped details, primary action, secondary actions. Allow Dynamic Type wrapping and scrolling. Targets minimum44, primary56.'}];
  i++;
}
if(oldBoard){for(const t of oldBoard.children.filter(n=>n.type==='TEXT')){page.appendChild(t);t.x=112;t.y=80+(t.name.startsWith('SkyCompanion')?0:55);}oldBoard.remove();}
const destinations=Object.fromEntries(Object.entries(screens).map(([k,v])=>[k,v.id]));
const links=[
  {
    "id": "6:8",
    "dest": "Home"
  },
  {
    "id": "6:15",
    "dest": "Permission"
  },
  {
    "id": "6:20",
    "dest": "Permission"
  },
  {
    "id": "6:25",
    "dest": "Sound"
  },
  {
    "id": "6:27",
    "dest": "Home"
  },
  {
    "id": "6:39",
    "dest": "Drone"
  },
  {
    "id": "6:41",
    "dest": "Description"
  },
  {
    "id": "6:43",
    "dest": "Video"
  },
  {
    "id": "6:45",
    "dest": "Settings"
  },
  {
    "id": "6:50",
    "dest": "Home"
  },
  {
    "id": "6:60",
    "dest": "ROI"
  },
  {
    "id": "6:65",
    "dest": "Preparing"
  },
  {
    "id": "6:70",
    "dest": "Home"
  },
  {
    "id": "6:83",
    "dest": "Description"
  },
  {
    "id": "6:85",
    "dest": "Muted"
  },
  {
    "id": "6:87",
    "dest": "Paused"
  },
  {
    "id": "6:89",
    "dest": "Home"
  },
  {
    "id": "6:94",
    "dest": "Home"
  },
  {
    "id": "6:101",
    "dest": "Playback"
  },
  {
    "id": "6:112",
    "dest": "Home"
  },
  {
    "id": "6:119",
    "dest": "Sound"
  },
  {
    "id": "6:124",
    "dest": "Commands"
  },
  {
    "id": "6:129",
    "dest": "Delete"
  },
  {
    "id": "6:131",
    "dest": "Diagnostics"
  },
  {
    "id": "6:135",
    "dest": "Home"
  },
  {
    "id": "6:148",
    "dest": "Session"
  },
  {
    "id": "6:163",
    "dest": "Drone"
  },
  {
    "id": "6:165",
    "dest": "Description"
  },
  {
    "id": "6:167",
    "dest": "Settings"
  }
];
const complete=links.filter(l=>destinations[l.dest]);
for(const link of complete){const node=await figma.getNodeByIdAsync(link.id);await node.setReactionsAsync([{trigger:{type:'ON_CLICK'},actions:[{type:'NODE',destinationId:destinations[link.dest],navigation:'NAVIGATE',transition:null}]}]);}
return {screens,connected:complete.length,pending:links.filter(l=>!destinations[l.dest]),fontFamilies:[...new Set(page.findAllWithCriteria({types:['TEXT']}).map(t=>t.fontName.family))],missingFonts:page.findAllWithCriteria({types:['TEXT']}).filter(t=>t.hasMissingFont).map(t=>t.id)};
// Next: create top-level destination frames for remaining pending links from
// interactive-preview.html, wire them, and inspect a composition screenshot.
// Also rebind/edit component text properties after fonts are fixed.
