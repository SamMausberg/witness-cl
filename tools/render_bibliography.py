"""Render this repository's brace-valued BibTeX subset without requiring bibtex.

The original .bib remains available for submission templates. This deliberately
small renderer rejects unsupported field syntax rather than silently dropping it.
"""
from pathlib import Path
import re
ROOT=Path(__file__).resolve().parents[1]

def read_braces(text, pos):
    if text[pos]!='{': raise ValueError('expected brace-delimited value')
    start=pos+1;depth=1;pos+=1
    while pos<len(text):
        if text[pos]=='{':depth+=1
        elif text[pos]=='}':depth-=1
        if depth==0:return text[start:pos],pos+1
        pos+=1
    raise ValueError('unbalanced BibTeX braces')

def parse(text):
    out=[];pos=0
    while True:
        match=re.search(r'@(\w+)\s*\{\s*([^,\s]+)\s*,',text[pos:])
        if not match:break
        typ,key=match.groups();pos+=match.end();fields={}
        while True:
            while pos<len(text) and text[pos] in ' \t\n\r,':pos+=1
            if text[pos]=='}':pos+=1;break
            match=re.match(r'(\w+)\s*=\s*',text[pos:])
            if not match:raise ValueError('unsupported field syntax near '+text[pos:pos+50])
            field=match.group(1);pos+=match.end()
            value,pos=read_braces(text,pos);fields[field]=value
        out.append((key,fields))
    return out

def authors(value):
    names=[]
    for name in value.split(' and '):
        if name=='others':names.append('et al.');continue
        if ',' in name:
            last,first=name.split(',',1);name=first.strip()+' '+last.strip()
        names.append(name)
    return ', '.join(names)

def main():
    entries=parse((ROOT/'paper/references.bib').read_text())
    lines=[r'\begin{thebibliography}{99}']
    for key,f in entries:
        lines += [r'\bibitem{'+key+'}', authors(f['author'])+'.',f['title']+'.']
        if 'journal' in f:
            venue=r'\emph{'+f['journal']+'}'
            if 'volume'in f:venue+=', '+f['volume']
            if 'number'in f:venue+='('+f['number']+')'
            if 'pages'in f:venue+=':'+f['pages']
            lines.append(venue+', '+f['year']+'.')
        elif 'booktitle' in f:
            lines.append(r'In \emph{'+f['booktitle']+'}, '+f['year']+'.')
        else:lines.append(f['year']+'.')
        if 'note'in f:lines.append(f['note']+'.')
        if 'url'in f:lines.append(r'\url{'+f['url']+'}.')
        elif 'doi'in f:lines.append(r'\url{https://doi.org/'+f['doi']+'}.')
        lines.append('')
    lines.append(r'\end{thebibliography}')
    (ROOT/'paper/references_formatted.tex').write_text('\n'.join(lines)+'\n')
    print(f'{len(entries)} bibliography entries rendered from references.bib.')
if __name__=='__main__':main()
