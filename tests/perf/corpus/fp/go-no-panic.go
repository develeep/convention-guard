package main

func run(ok bool) {
	if !ok {
		panic("unreachable")
	}
	// panic("legacy guard")
	msg := "panic(here) is only text"
	_ = msg
}
