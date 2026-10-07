// Headless scheduling replaces browser frame budgets, not graph algorithms.
export const queuedTasks: any[] = [];
export class AsyncScheduler {
  constructor(_budget: any) {}
  schedule(task: any, _done: any, _owner: any) { queuedTasks.push(task); }
  clear() { queuedTasks.length = 0; }
}
export function drainTasks() {
  let budget = 10_000_000;
  while (queuedTasks.length) {
    const task = queuedTasks.shift();
    while (!task.step(10_000)) {
      budget -= 10_000;
      if (budget <= 0) throw new Error('Превышен бюджет поиска колец; используйте --no-cycles');
    }
  }
}
