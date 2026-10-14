// Presentation groups over stable resource IDs; never change holdings or bag type.
export const warehouseCategories=[
 ['all','全部'],['currency','货币灵石'],['mineral','矿石金属'],['wood','木材石料'],
 ['herb','药材'],['crop','灵植食材'],['meal','灵膳'],['feed','饲料'],
 ['animal','兽材水产'],['dungeon','秘境材料'],['processed','加工材料'],['other','其他']
];
const groups={
 currency:new Set(['coins','spirit_stone_low','spirit_stone_mid','spirit_stone_high','spirit_stone_supreme','spirit_stone_immortal']),
 mineral:new Set(['ore','copper','ingot','gem','jade','red_ore','spirit_ore','spirit_ingot','star_dust','star_ore','star_ingot','spirit_iron_ore','spirit_iron_ingot','refined_iron_ingot','purple_copper','black_gold','fire_pattern_stone','water_spirit_stone','wood_spirit_stone','green_spirit_stone','condensed_spirit_crystal','cold_jade_ore','ice_crystal_ore']),
 wood:new Set(['wood','ordinary_wood','raw_wood','plank','spirit_plank','stone','brick']),
 herb:new Set(['herb','rare_herb','dewleaf','moonleaf','divine_leaf','material_1_1','material_2_1','material_3_0','material_4_1','sect_crop_13','sect_crop_14']),
 crop:new Set(['grain','spirit_fruit','spring_water','fertilizer']),
 meal:new Set(['food']),
 feed:new Set(['feed']),
 animal:new Set(['egg','fish','meat','milk','hide','soft_wool','beast_bone','beast_sinew','beast_core','spirit_beast_blood','essence']),
 dungeon:new Set(['material_3_1','moon_pearl','stone_core']),
 processed:new Set(['cloth','fiber','silk','parts','crafting_essence','equipment_blank','sect_lining','sect_shell_part','sect_bone_frame','sect_nurture_agent'])
};
export function warehouseCategoryFor(id,row={}){
 if(['pill','equipment'].includes(row.category))return row.category;
 for(const [category,ids]of Object.entries(groups))if(ids.has(id))return category;
 if(id.startsWith('meal_'))return 'meal';
 if(id.startsWith('beast_feed_')||id.startsWith('fish_feed_'))return 'feed';
 if(id.startsWith('sect_crop_')||id.startsWith('seed_'))return 'crop';
 if(id.startsWith('sect_product_'))return 'animal';
 if(id.startsWith('thorn_')||id.startsWith('red_copper_mine_material_')||id.startsWith('mist_marsh_material_')||id.startsWith('cold_jade_cave_material_'))return 'dungeon';
 if(row.category==='herb')return 'herb';
 return 'other';
}
