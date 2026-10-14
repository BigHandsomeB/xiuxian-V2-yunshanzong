// Entry layout is presentation only. Presence here never builds/unlocks a Domain building.
export const regions=[
 {name:'山门与宗务',flavor:'云阶初起，宗门有序',tone:'stone',buildings:[['gate','山门','门'],['hall','宗务殿','印'],['house','弟子居','舍'],['kitchen','灵膳房','食']]},
 {name:'山间生息',flavor:'灵草沐雨，山泉养灵',tone:'jade',buildings:[['garden','灵植园','叶'],['pasture','御兽苑','兽'],['abyss','灵渊','渊'],['mountain','后山','石']]},
 {name:'丹火与百工',flavor:'一炉丹火，一寸匠心',tone:'copper',buildings:[['alchemy','丹鼎阁','丹'],['forge','炼器阁','器'],['workshop','百工坊','工'],['construction','营造司','筑']]},
 {name:'万宝与问道',flavor:'藏万物于匣，问大道于峰',tone:'indigo',buildings:[['warehouse','万宝库','匣'],['market','万宝楼','宝'],['dao','问道峰','道'],['techniques','功法阁','卷']]}
];
export const buildingEntries=regions.flatMap(r=>r.buildings.map(([id,name,glyph])=>({id,name,glyph,tone:r.tone})));
export function entryFor(id){return buildingEntries.find(row=>row.id===id);}

export function definitionFor(id){return ({kitchen:"canteen",construction:"builders",mountain:"forest",abyss:"spring",market:"trading",dao:"cave",workshop:"woodshop"})[id]||id;}
