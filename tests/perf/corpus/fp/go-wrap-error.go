package main

import "fmt"

func wrap(err error) error {
	if err != nil {
		return fmt.Errorf("load failed: %v", err)
	}
	// return fmt.Errorf("save failed: %v", err)
	hint := "use fmt.Errorf(\"x: %v\", err) with %w instead"
	_ = hint
	return nil
}
