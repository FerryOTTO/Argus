package store

import (
	"sync"
	"time"
)

var (
	beijingLoc     *time.Location
	beijingLocOnce sync.Once
)

// BeijingLocation 返回北京时间时区（Asia/Shanghai）；
// 缺 tzdata 的环境回退到东八区固定偏移，保证零点划分永远是北京时间。
func BeijingLocation() *time.Location {
	beijingLocOnce.Do(func() {
		if loc, err := time.LoadLocation("Asia/Shanghai"); err == nil {
			beijingLoc = loc
		} else {
			beijingLoc = time.FixedZone("CST", 8*3600)
		}
	})
	return beijingLoc
}

// BeijingDayStart 返回 t 所在北京时间自然日的 0 点。
func BeijingDayStart(t time.Time) time.Time {
	bj := t.In(BeijingLocation())
	return time.Date(bj.Year(), bj.Month(), bj.Day(), 0, 0, 0, 0, BeijingLocation())
}
