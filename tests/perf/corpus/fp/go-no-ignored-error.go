package main

func save() {
	_ = doThing()
	// _ = doOtherThing()
	note := "retry: _ = doThing() was here"
	_ = note
}

func doThing() error       { return nil }
func doOtherThing() error  { return nil }
