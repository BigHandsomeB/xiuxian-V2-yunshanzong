// Text from Domain/Manifest always enters the DOM as text, never markup.
export function el(tag,className='',text){const node=document.createElement(tag);const listen=node.addEventListener.bind(node);node.__eventBindings=[];node.addEventListener=(type,callback,options)=>{const record={type,callback,options};node.__eventBindings.push(record);listen(type,event=>record.callback.call(node,event),options);};if(className)node.className=className;if(text!==undefined)node.textContent=String(text);return node;}
export function link(text,href,className=''){const node=el('a',className,text);node.href=href;return node;}
export function button(text,onClick,className=''){const node=el('button',className,text);node.type='button';node.__onClick=onClick;node.addEventListener('click',event=>node.__onClick?.(event));return node;}
export function heading(title,subtitle,back){const head=el('header','screen-heading');if(back)head.append(link('‹ 返回',back,'back-link'));head.append(el('h1','',title));if(subtitle)head.append(el('p','',subtitle));return head;}
export function empty(message='此处尚未开放',detail=''){const node=el('div','empty-state');node.append(el('span','empty-mark','◇'),el('p','',message));if(detail)node.append(el('small','',detail));return node;}
export function status(text){return el('span','status-badge',text);}
export function facts(rows){const list=el('dl','facts');for(const [name,value]of rows){list.append(el('dt','',name),el('dd','',value));}return list;}
