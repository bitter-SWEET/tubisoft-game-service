import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import java.util.*;

// Breadth-first inventory of statically resolved direct call sites.
// Args: maximum depth, then entry addresses. Indirect calls remain unresolved.
public class FlowInventory extends GhidraScript {
  private static class Entry {
    final Function fn;
    final int depth;
    Entry(Function fn, int depth) { this.fn = fn; this.depth = depth; }
  }

  public void run() throws Exception {
    String[] args = getScriptArgs();
    if (args.length < 2) throw new IllegalArgumentException("depth root...");
    int maxDepth = Integer.parseInt(args[0]);
    if (maxDepth < 0 || maxDepth > 4) throw new IllegalArgumentException("depth 0..4");
    Deque<Entry> queue = new ArrayDeque<>();
    Set<Address> seen = new HashSet<>();
    for (int i = 1; i < args.length; i++) {
      Function f = getFunctionContaining(toAddr(args[i]));
      if (f == null) println("MISSING ROOT " + args[i]);
      else queue.add(new Entry(f, 0));
    }
    int callsites = 0, indirect = 0;
    while (!queue.isEmpty() && !monitor.isCancelled()) {
      Entry e = queue.removeFirst();
      if (!seen.add(e.fn.getEntryPoint())) continue;
      println("FUNCTION depth=" + e.depth + " entry=" + e.fn.getEntryPoint() + " name=" + e.fn.getName());
      InstructionIterator ins = currentProgram.getListing().getInstructions(e.fn.getBody(), true);
      while (ins.hasNext()) {
        Instruction instruction = ins.next();
        if (!instruction.getFlowType().isCall()) continue;
        Address[] flows = instruction.getFlows();
        if (flows.length == 0) {
          indirect++;
          println("INDIRECT " + instruction.getAddress() + " " + instruction);
          continue;
        }
        for (Address target : flows) {
          callsites++;
          Function callee = getFunctionAt(target);
          println("CALL " + instruction.getAddress() + " -> " + target + " " + (callee == null ? "unresolved" : callee.getName()));
          if (callee != null && e.depth < maxDepth && !seen.contains(callee.getEntryPoint()))
            queue.addLast(new Entry(callee, e.depth + 1));
        }
      }
    }
    println("SUMMARY functions=" + seen.size() + " resolved_calls=" + callsites + " indirect_calls=" + indirect);
  }
}
