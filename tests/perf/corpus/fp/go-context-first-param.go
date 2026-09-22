package main

import "context"

func Fetch(id string, ctx context.Context) error {
	_ = ctx
	return nil
}

// func Store(id string, ctx context.Context) error { return nil }

var doc = `
func Remove(id string, ctx context.Context) error { return nil }
`
