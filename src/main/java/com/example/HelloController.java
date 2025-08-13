package com.example;

import org.springframework.web.bind.annotation.*;
import java.time.Instant;
import java.util.Map;

@RestController
public class HelloController {

  @GetMapping("/")
  public Map<String,Object> root() {
    return Map.of(
      "message", "Hello from Cloud Run 👋",
      "time", Instant.now().toString()
    );
  }

  @GetMapping("/health")
  public Map<String,String> health() {
    return Map.of("status", "ok");
  }

  // echo something: /echo?msg=hey
  @GetMapping("/echo")
  public Map<String,String> echo(@RequestParam(defaultValue = "none") String msg) {
    return Map.of("echo", msg);
  }
}
