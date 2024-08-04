from datetime import date, timedelta
from rest_framework.decorators import action
from rest_framework import viewsets, status
from rest_framework.response import Response
from django.utils.dateparse import parse_date
from django.contrib.auth.models import AnonymousUser
from django.db.models import Q

from .models import UserRoutine, PersonalSchedule, MonthlyTitle, UserRoutineCompletion
from .serializers import UserRoutineSerializer, PersonalScheduleSerializer, MonthlyTitleSerializer, UserRoutineCompletionSerializer
from rest_framework.permissions import AllowAny
from rest_framework.permissions import IsAuthenticated
from routine.models import Routine
from django.core.exceptions import ValidationError

from rest_framework.views import APIView
from datetime import datetime

class CalendarViewSet(viewsets.ViewSet):
    permission_classes = [IsAuthenticated]

    def get_user(self, request):
        user = request.user
        if not user.is_authenticated:
            return None
        return user
    
    @action(detail=False, methods=['get'])
    def daily(self, request, date=None):
        date_obj = parse_date(date)
        if not date_obj:
            return Response({"detail": "Invalid date format"}, status=status.HTTP_400_BAD_REQUEST)

        # 개인 일정 가져오기
        schedules = PersonalSchedule.objects.filter(user=request.user, date=date_obj)
        schedule_serializer = PersonalScheduleSerializer(schedules, many=True)

        # 루틴 가져오기
        user_routines = UserRoutine.objects.filter(user=request.user, start_date__lte=date_obj, end_date__gte=date_obj)
        routine_serializer = UserRoutineSerializer(user_routines, many=True, context={'request': request, 'selected_date': date_obj})

        data = {
                'schedules': schedule_serializer.data,
                'routines': routine_serializer.data
            }

        return Response(data, status=status.HTTP_200_OK)

    @action(detail=False, methods=['post'])
    def create_schedule(self, request, date=None):
        date_obj = parse_date(date)
        if not date_obj:
            return Response({"detail": "Invalid date format"}, status=status.HTTP_400_BAD_REQUEST)

        data = request.data
        data['user'] = request.user.id
        data['date'] = date_obj

        serializer = PersonalScheduleSerializer(data=data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=['patch'])
    def update_schedule(self, request, date=None):
        # 날짜 파싱
        date_obj = parse_date(date)
        if not date_obj:
            return Response({"detail": "Invalid date format"}, status=status.HTTP_400_BAD_REQUEST)

        # 요청 본문에서 필수 ID와 선택적 필드 가져오기
        schedule_id = request.data.get('id')
        if not schedule_id:
            return Response({"detail": "ID is required"}, status=status.HTTP_400_BAD_REQUEST)

        # 해당 날짜와 사용자에 대한 PersonalSchedule 필터링
        schedules = PersonalSchedule.objects.filter(user=request.user, date=date_obj)

        # ID에 해당하는 스케줄 찾기
        try:
            schedule = schedules.get(id=schedule_id)
        except PersonalSchedule.DoesNotExist:
            return Response({"detail": "PersonalSchedule not found"}, status=status.HTTP_404_NOT_FOUND)

        # 업데이트할 데이터 준비
        updated_data = {}
        if 'title' in request.data:
            updated_data['title'] = request.data['title']
        if 'description' in request.data:
            updated_data['description'] = request.data['description']
        if 'completed' in request.data:
            updated_data['completed'] = request.data['completed']

        # Serializer를 사용하여 데이터 검증 및 저장
        serializer = PersonalScheduleSerializer(schedule, data=updated_data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    
    @action(detail=True, methods=['post'])
    def add_routine(self, request, id=None):
        user = self.get_user(request)

        if user is None:
            return Response({'error': 'Authentication credentials were not provided.'}, status=status.HTTP_403_FORBIDDEN)

        try:
            routine = Routine.objects.get(id=id)
        except Routine.DoesNotExist:
            return Response({'error': 'Routine not found'}, status=status.HTTP_404_NOT_FOUND)

        start_date_str = request.data.get('start_date')
        end_date_str = request.data.get('end_date')

        if not start_date_str or not end_date_str:
            return Response({'error': 'Start date and end date are required.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            start_date = parse_date(start_date_str)
            end_date = parse_date(end_date_str)
            if start_date is None or end_date is None:
                raise ValueError("Invalid date format")
        except ValueError:
            return Response({'error': 'Invalid date format'}, status=status.HTTP_400_BAD_REQUEST)

        if start_date > end_date:
            return Response({'error': 'End date must be after start date.'}, status=status.HTTP_400_BAD_REQUEST)

        if end_date < date.today():
            return Response({'error': 'End date cannot be in the past.'}, status=status.HTTP_400_BAD_REQUEST)

        # 동일한 날짜에 동일한 루틴이 이미 존재하는지 확인
        existing_routine = UserRoutine.objects.filter(
            user=user,
            routine=routine,
            start_date__lte=start_date,
            end_date__gte=start_date
        ).exists()

        if existing_routine:
            return Response({'error': 'A routine with the same dates already exists for this user on this date.'}, status=status.HTTP_400_BAD_REQUEST)

        user_routine = UserRoutine.objects.create(
            user=user,
            routine=routine,
            start_date=start_date,
            end_date=end_date
        )

        response_data = {
            'id': routine.id,
            'status': status.HTTP_201_CREATED
        }

        return Response(response_data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=['get'])
    def monthly_calendar(self, request, month=None):
        user = self.get_user(request)
        
        if user is None:
            return Response({'error': '인증 자격 증명이 제공되지 않았습니다.'}, status=status.HTTP_403_FORBIDDEN)
        
        if not month:
            return Response({'error': '월 파라미터가 필요합니다.'}, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            selected_month = datetime.strptime(month, '%Y-%m')
        except ValueError:
            return Response({'error': '잘못된 월 형식입니다. 형식은 YYYY-MM 입니다.'}, status=status.HTTP_400_BAD_REQUEST)
        
        # 해당 월의 첫 날과 마지막 날을 계산합니다.
        start_date = selected_month.replace(day=1)
        end_date = (start_date + timedelta(days=31)).replace(day=1) - timedelta(days=1)
        
        # 날짜별로 모든 루틴과 스케줄이 완료되었는지를 체크할 리스트 초기화
        completed_dates = []
        
        # 월 내의 모든 날짜를 확인합니다.
        for single_date in (start_date + timedelta(n) for n in range((end_date - start_date).days + 1)):
            # 해당 날짜에 대한 루틴과 스케줄 가져오기
            routines_for_date = UserRoutineCompletion.objects.filter(
                user=user,
                date=single_date
            )
            schedules_for_date = PersonalSchedule.objects.filter(
                user=user,
                date=single_date
            )
            
            # 모든 루틴과 스케줄이 완료되었는지 체크
            all_routines_completed = all(routine.completed for routine in routines_for_date)
            all_schedules_completed = all(schedule.completed for schedule in schedules_for_date)
            
            if all_routines_completed and all_schedules_completed:
                completed_dates.append(single_date.isoformat())
        
        return Response(completed_dates, status=status.HTTP_200_OK)

    # @action(detail=False, methods=['get'])
    # def check_star(self, request, date=None):
    #     user = self.get_user(request)

    #     if user is None:
    #         return Response({'error': 'Authentication credentials were not provided.'}, status=status.HTTP_403_FORBIDDEN)

    #     if not date:
    #         return Response({'error': 'Date parameter is required'}, status=status.HTTP_400_BAD_REQUEST)

    #     try:
    #         selected_date = parse_date(date)
    #         if selected_date is None:
    #             raise ValueError("Invalid date format")
    #     except (ValueError, TypeError, OverflowError, ValidationError):
    #         return Response({'error': 'Invalid date format'}, status=status.HTTP_400_BAD_REQUEST)

    #     # 해당 날짜의 모든 루틴을 가져옴
    #     user_routines = UserRoutine.objects.filter(
    #         user=user,
    #         start_date__lte=selected_date,
    #         end_date__gte=selected_date
    #     )

    #     # 모든 루틴이 완료되었는지 확인
    #     all_completed = all(UserRoutineCompletion.objects.filter(
    #         user=user,
    #         routine=user_routine,
    #         date=selected_date,
    #         completed=True
    #     ).exists() for user_routine in user_routines)

    #     return Response({'check_star': all_completed}, status=status.HTTP_200_OK)

class UpdateRoutineCompletionView(APIView):
    permission_classes = [IsAuthenticated]

    def patch(self, request, date):
        try:
            user = request.user
            date_obj = datetime.strptime(date, '%Y-%m-%d').date()
            routine_id = request.data.get('routine_id')
            completed = request.data.get('completed')

            if routine_id is None or completed is None:
                return Response({"detail": "Missing routine_id or completed field."}, status=status.HTTP_400_BAD_REQUEST)

            try:
                completion = UserRoutineCompletion.objects.get(user=user, routine_id=routine_id, date=date_obj)
                completion.completed = completed
                completion.save()
            except UserRoutineCompletion.DoesNotExist:
                return Response({"detail": "UserRoutineCompletion not found."}, status=status.HTTP_404_NOT_FOUND)
            
            return Response({"status": "Routine completion status updated successfully"}, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({"detail": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)