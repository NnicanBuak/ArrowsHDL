"""Independent rule model used only to check physical output measurements."""
from collections import deque
from .context import DIRECTIONS

def flood(size,mines,opened,clicks):
    opened=set(opened);todo=deque(clicks)
    while todo:
        i=todo.popleft()
        if i in opened or i in mines:continue
        opened.add(i)
        x,y=i%size,i//size
        ns=[(y+dy)*size+x+dx for dx,dy in DIRECTIONS if 0<=x+dx<size and 0<=y+dy<size]
        if not any(n in mines for n in ns):todo.extend(ns)
    return opened
