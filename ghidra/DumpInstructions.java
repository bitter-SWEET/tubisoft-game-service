import ghidra.app.script.GhidraScript;
import ghidra.program.model.listing.*;
import java.io.BufferedWriter;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;

// Export every currently recognized instruction, preserving function entry
// markers and raw instruction bytes. Data and unrecognized code are omitted.
public class DumpInstructions extends GhidraScript {
  public void run() throws Exception {
    String[] args = getScriptArgs();
    if (args.length != 1) throw new IllegalArgumentException("absolute output path");
    Path output = Paths.get(args[0]).toAbsolutePath().normalize();
    Path allowed = Paths.get(getSourceFile().getAbsolutePath()).getParent().getParent()
        .resolve("work/research").toAbsolutePath().normalize();
    if (!output.startsWith(allowed)) throw new IllegalArgumentException("output must be under work/research");
    long count = 0, functions = 0;
    try (BufferedWriter out = Files.newBufferedWriter(output, StandardCharsets.UTF_8)) {
      out.write("Recognized instructions only; data and unidentified code are omitted.\n");
      InstructionIterator it = currentProgram.getListing().getInstructions(true);
      while (it.hasNext() && !monitor.isCancelled()) {
        Instruction ins = it.next();
        Function f = getFunctionAt(ins.getAddress());
        if (f != null) {
          out.write("\nFUNCTION " + f.getEntryPoint() + " " + f.getName() + " " + f.getBody() + "\n");
          functions++;
        }
        StringBuilder bytes = new StringBuilder();
        for (byte b : ins.getBytes()) bytes.append(String.format("%02x", b & 0xff));
        out.write(ins.getAddress() + " " + bytes + " " + ins.toString() + "\n");
        count++;
      }
    }
    if (monitor.isCancelled()) throw new InterruptedException("instruction export cancelled");
    println("EXPORTED instructions=" + count + " function_entries=" + functions + " path=" + output);
  }
}
