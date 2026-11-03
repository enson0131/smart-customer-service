import data from "./index.generated.json";
type Source = {title:string; excerpt:string};
const {chunks, df, avg} = data as unknown as {chunks:[Source,Record<string,number>][],df:Record<string,number>,avg:number};
export function search(query:string) {
  const words = query.toLowerCase().match(/[\u3400-\u9fff]+|[a-z0-9]+/g) ?? [];
  const terms = new Set(words.flatMap(word => /^[a-z0-9]+$/.test(word) || word.length===1
    ? [word] : Array.from({length:word.length-1}, (_,i)=>word.slice(i,i+2))));
  const ranked = chunks.map(([source, counts]) => {
    const matches = [...terms].filter(t=>Object.hasOwn(counts,t));
    const length = Object.values(counts).reduce((a,b)=>a+b,0);
    const score = matches.length < terms.size*.22 ? 0 : matches.reduce((sum,t)=>
      sum + Math.log1p((chunks.length-df[t]+.5)/(df[t]+.5))*counts[t]*2.2/(counts[t]+1.2*(.25+.75*length/avg)),0);
    return {source,score};
  }).filter(x=>x.score>0).sort((a,b)=>b.score-a.score);
  return ranked.slice(0,2).filter(x=>x.score>=ranked[0].score*.65).map(x=>x.source);
}
