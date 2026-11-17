#include <stdlib.h>
#include <stdio.h>
#include <time.h>
#include <pthread.h>
#include <sched.h>
int main(int c,char**v){ struct sched_param sp={.sched_priority=50}; pthread_setschedparam(pthread_self(),SCHED_FIFO,&sp);
 long per=c>1?atol(v[1]):1000000; struct timespec t,n,r; clock_getres(CLOCK_MONOTONIC,&r); printf("res=%ldns period=%ldns\n",r.tv_nsec,per);
 clock_gettime(CLOCK_MONOTONIC,&t); long miss=0,worst=0;
 for(int i=0;i<2000;i++){ t.tv_nsec+=per; while(t.tv_nsec>=1000000000){t.tv_nsec-=1000000000;t.tv_sec++;}
  clock_nanosleep(CLOCK_MONOTONIC,TIMER_ABSTIME,&t,NULL); clock_gettime(CLOCK_MONOTONIC,&n);
  long late=(n.tv_sec-t.tv_sec)*1000000000L+(n.tv_nsec-t.tv_nsec); if(late>worst)worst=late; if(late>200000)miss++; }
 printf("late>200us: %ld/2000 worst=%ldus\n",miss,worst/1000); return 0;}
